"""Document chunk store and lexical search (INT-23).

A standalone local SQLite file with an FTS5 index ranked by ``bm25()``. A chunk id hashes the document,
page, character span and chunker version, so re-indexing keeps ids and a new chunker adds rows. Chunk
text is untrusted document content; a citation that does not resolve fails closed.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import closing
from dataclasses import astuple, dataclass, fields, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from etf_cockpit.data.local_storage import connect_local_database

CHUNK_STORE_NAME = "document_chunks.sqlite3"
CHUNKER_VERSION = "pages-v1"
CHUNK_CHARS = 1200


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    chunker_version: str
    document_sha256: str
    source_id: str
    published_at: str
    known_at: str
    page: int
    char_start: int  # page-relative character span
    char_end: int
    text: str


def chunk_pages(
    pages: Sequence[str],
    *,
    document_sha256: str,
    source_id: str,
    published_at: str,
    known_at: str,
    chunker_version: str = CHUNKER_VERSION,
) -> list[DocumentChunk]:
    """Split each page into spans of at most ``CHUNK_CHARS``, ending at whitespace where one exists."""

    chunks = []
    for page, text in enumerate(pages, start=1):
        start = 0
        while start < len(text):
            end = len(text) if len(text) - start <= CHUNK_CHARS else (text.rfind(" ", start + 1, start + CHUNK_CHARS) + 1 or start + CHUNK_CHARS)
            identity = json.dumps([document_sha256, page, start, end, chunker_version]).encode("utf-8")
            chunks.append(DocumentChunk(hashlib.sha256(identity).hexdigest(), chunker_version, document_sha256, source_id,
                                        _utc(published_at), _utc(known_at), page, start, end, text[start:end]))
            start = end
    return chunks


def index_document(path: Path, chunks: Sequence[DocumentChunk]) -> int:
    """Store the chunks not stored yet; returns how many were new."""

    added = 0
    with closing(_connect(path)) as connection:
        for chunk in chunks:
            row = astuple(replace(chunk, published_at=_utc(chunk.published_at), known_at=_utc(chunk.known_at)))
            inserted = connection.execute(f"INSERT OR IGNORE INTO chunks VALUES ({', '.join('?' * len(_COLUMNS))})", row)
            if inserted.rowcount:
                connection.execute("INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)", (chunk.chunk_id, chunk.text))
                added += 1
    return added


def search(path: Path, query: str, *, as_of: str, limit: int = 10, chunker_version: str = CHUNKER_VERSION) -> dict[str, object]:
    """bm25-ranked chunks known at ``as_of``; ``unavailable`` when the store or FTS5 is missing."""

    terms = " ".join(f'"{term}"' for term in re.findall(r"\w+", query))
    if not Path(path).is_file():
        return {"status": "unavailable", "reason": "no document chunk store", "hits": []}
    try:
        with closing(_connect(path)) as connection:
            rows = connection.execute(
                f"SELECT {', '.join('c.' + name for name in _COLUMNS)} FROM chunks_fts JOIN chunks c USING (chunk_id) "
                "WHERE chunks_fts MATCH ? AND c.known_at <= ? AND c.chunker_version = ? ORDER BY bm25(chunks_fts) LIMIT ?",
                (terms, _utc(as_of), chunker_version, limit),
            ).fetchall() if terms else []
    except sqlite3.OperationalError as exc:  # FTS5 missing from this SQLite build
        return {"status": "unavailable", "reason": str(exc), "hits": []}
    return {"status": "available", "reason": None, "hits": [dict(zip(_COLUMNS, row)) for row in rows]}


def resolve(path: Path, chunk_id: str, document_sha256: str) -> DocumentChunk | None:
    """The cited chunk, or None when it is missing, belongs to another document or fails its id check."""

    if not Path(path).is_file():
        return None
    with closing(_connect(path)) as connection:
        row = connection.execute(f"SELECT {', '.join(_COLUMNS)} FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
    if row is None:
        return None
    chunk = DocumentChunk(*row)
    identity = json.dumps([chunk.document_sha256, chunk.page, chunk.char_start, chunk.char_end, chunk.chunker_version])
    if (chunk.document_sha256 != document_sha256 or hashlib.sha256(identity.encode("utf-8")).hexdigest() != chunk_id
            or chunk.page < 1 or not 0 <= chunk.char_start < chunk.char_end or len(chunk.text) != chunk.char_end - chunk.char_start):
        return None
    return chunk


_COLUMNS = tuple(field.name for field in fields(DocumentChunk))


def _connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = connect_local_database(Path(path))
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS chunks (chunk_id TEXT PRIMARY KEY, chunker_version TEXT NOT NULL, "
            "document_sha256 TEXT NOT NULL, source_id TEXT NOT NULL, published_at TEXT NOT NULL, known_at TEXT NOT NULL, "
            "page INTEGER NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL, text TEXT NOT NULL)"
        )
        connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, text)")
    except sqlite3.Error:
        connection.close()
        raise
    return connection


def _utc(value: str) -> str:
    """One sortable UTC text form, so ``known_at <= as_of`` compares instants."""

    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must carry a time zone")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
