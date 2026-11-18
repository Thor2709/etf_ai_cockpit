"""Dense retrieval over the document chunk store (INT-25, optional ``retrieval`` extra).

Vectors are keyed by chunk id, index version and model revision, and live in the chunk store file. The
embedding model is loaded only from a local directory whose files match the sha256 pins in
``configs/supply_chain_intake.yaml``; nothing is downloaded. Without fastembed or the weights every dense
call returns ``unavailable`` with the reason, and search stays lexical. Hybrid search (reciprocal-rank
fusion) stays off until the evaluation report in ``scripts/eval_retrieval.py`` shows it is not worse than
lexical search. Reranking has no approved weights, so it is unavailable.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import fields
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

import numpy as np

from etf_cockpit.core.paths import CODE_CONFIG_DIR, MODEL_DIR
from etf_cockpit.data import document_chunks as chunk_store
from etf_cockpit.data.local_storage import connect_local_database
from etf_cockpit.governance.supply_chain_intake import load_supply_chain_intake

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
WEIGHT_SET = "bge_small_en_v15_onnx_q"
EMBEDDING_MODEL_DIR = MODEL_DIR / "fastembed" / "bge-small-en-v1.5-onnx-Q"
INDEX_VERSION = "dense-v1"
HYBRID_ENABLED = False  # set to True only from an evaluation report with hybrid_enabled=true
RRF_K = 60
CANDIDATES = 50
_HIT_FIELDS = tuple(field.name for field in fields(chunk_store.DocumentChunk))


class EmbeddingUnavailable(RuntimeError):
    """The package, the weights or a weight pin is missing; the message is the reason."""


@lru_cache(maxsize=1)
def _weight_rows() -> tuple[dict[str, Any], ...]:
    return tuple(row for row in load_supply_chain_intake(CODE_CONFIG_DIR / "supply_chain_intake.yaml")["components"] if row.get("weight_set") == WEIGHT_SET)


def pinned_files() -> dict[str, str]:
    """File name to sha256 of the approved embedding weight set, from the supply-chain intake registry."""

    return {str(row["file"]): str(row["sha256"]) for row in _weight_rows()}


def _model_revision() -> str:
    return str(_weight_rows()[0]["revision"])


def embedding_status() -> dict[str, object]:
    try:
        _embedder(Path(EMBEDDING_MODEL_DIR))
    except EmbeddingUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc)}
    return {"status": "available", "reason": None, "model_revision": _model_revision()}


def rerank_status() -> dict[str, object]:
    return {"status": "unavailable", "reason": "no reranker weights are approved or downloaded"}


@lru_cache(maxsize=2)
def _embedder(model_dir: Path) -> Any:
    pins = pinned_files()
    if not pins:
        raise EmbeddingUnavailable("no sha256 pins for the embedding weights in the supply-chain intake registry")
    # SOURCE.json is the download provenance note; fastembed never reads it.
    unpinned = sorted(
        item.relative_to(model_dir).as_posix() for item in model_dir.rglob("*")
        if item.is_file() and item.relative_to(model_dir).as_posix() not in {*pins, "SOURCE.json"}
    ) if model_dir.is_dir() else []
    if unpinned:
        raise EmbeddingUnavailable(f"model directory files are not pinned by sha256: {', '.join(unpinned)}")
    for name, expected in pins.items():
        path = model_dir / name
        if not path.is_file():
            raise EmbeddingUnavailable(f"embedding weight file is missing: {path}")
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                raise EmbeddingUnavailable(f"embedding weight file does not match its pinned sha256: {name}")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise EmbeddingUnavailable("fastembed is not installed (optional retrieval extra)") from exc
    try:
        return TextEmbedding(EMBEDDING_MODEL_NAME, specific_model_path=str(model_dir), local_files_only=True,
                             providers=["CPUExecutionProvider"])
    except Exception as exc:  # fastembed raises many types; any failure means no dense search
        raise EmbeddingUnavailable(f"fastembed could not load the local model: {exc}") from exc


def index_embeddings(path: Path) -> int:
    """Embed the chunks that have no vector for this index version and model revision; returns how many."""

    embedder = _embedder(Path(EMBEDDING_MODEL_DIR))
    revision = _model_revision()
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            "SELECT chunk_id, text FROM chunks WHERE chunk_id NOT IN "
            "(SELECT chunk_id FROM chunk_embeddings WHERE index_version = ? AND model_revision = ?)",
            (INDEX_VERSION, revision),
        ).fetchall()
        vectors = list(embedder.embed([text for _, text in rows])) if rows else []
        for (chunk_id, _), vector in zip(rows, vectors, strict=True):
            blob = np.asarray(vector, dtype="<f4")
            connection.execute("INSERT INTO chunk_embeddings VALUES (?, ?, ?, ?, ?)",
                               (chunk_id, INDEX_VERSION, revision, blob.size, blob.tobytes()))
    return len(rows)


def dense_search(
    path: Path, query: str, *, as_of: str, limit: int = 10, chunker_version: str = chunk_store.CHUNKER_VERSION,
) -> dict[str, object]:
    """Cosine-ranked chunks known at ``as_of``; ``unavailable`` with the reason when any of them has no vector."""

    if not Path(path).is_file():
        return {"status": "unavailable", "reason": "no document chunk store", "hits": []}
    try:
        embedder = _embedder(Path(EMBEDDING_MODEL_DIR))
    except EmbeddingUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc), "hits": []}
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            f"SELECT {', '.join('c.' + name for name in _HIT_FIELDS)}, e.vector FROM chunks c "
            "LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id AND e.index_version = ? AND e.model_revision = ? "
            "WHERE c.known_at <= ? AND c.chunker_version = ?",
            (INDEX_VERSION, _model_revision(), chunk_store._utc(as_of), chunker_version),
        ).fetchall()
    if not rows:
        return {"status": "unavailable", "reason": "no chunks known at as_of", "hits": []}
    missing = sum(row[-1] is None for row in rows)
    if missing:
        return {"status": "unavailable", "hits": [],
                "reason": f"{missing} chunks known at as_of have no embedding for this model revision; run index_embeddings"}
    if not re.findall(r"\w+", query):
        return {"status": "available", "reason": None, "hits": []}
    matrix = np.vstack([np.frombuffer(row[-1], dtype="<f4") for row in rows])
    query_vector = np.asarray(next(iter(embedder.query_embed(query))), dtype="<f4")
    scores = matrix @ query_vector / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_vector))
    order = np.argsort(-scores, kind="stable")[:limit]
    return {"status": "available", "reason": None, "hits": [dict(zip(_HIT_FIELDS, rows[i][:-1])) for i in order]}


def reciprocal_rank_fusion(rankings: Iterable[Sequence[str]], k: int = RRF_K) -> list[str]:
    """Ids ordered by the sum of ``1 / (k + rank)`` over the rankings; ties keep first-seen order."""

    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda chunk_id: -scores[chunk_id])


def hybrid_search(
    path: Path, query: str, *, as_of: str, limit: int = 10, chunker_version: str = chunk_store.CHUNKER_VERSION,
) -> dict[str, object]:
    """Lexical and dense rankings fused by reciprocal-rank fusion; ``unavailable`` when either side is."""

    window = max(CANDIDATES, limit)
    lexical: dict[str, Any] = chunk_store.search(path, query, as_of=as_of, limit=window, chunker_version=chunker_version)
    dense: dict[str, Any] = dense_search(path, query, as_of=as_of, limit=window, chunker_version=chunker_version)
    for part in (lexical, dense):
        if part["status"] != "available":
            return {"status": "unavailable", "reason": part["reason"], "hits": []}
    by_id = {hit["chunk_id"]: hit for hit in [*dense["hits"], *lexical["hits"]]}
    order = reciprocal_rank_fusion([[hit["chunk_id"] for hit in lexical["hits"]], [hit["chunk_id"] for hit in dense["hits"]]])
    return {"status": "available", "reason": None, "hits": [by_id[chunk_id] for chunk_id in order[:limit]]}


def _connect(path: Path) -> sqlite3.Connection:
    connection = connect_local_database(Path(path))
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS chunk_embeddings (chunk_id TEXT NOT NULL, index_version TEXT NOT NULL, "
            "model_revision TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL, "
            "PRIMARY KEY (chunk_id, index_version, model_revision))"
        )
    except sqlite3.Error:
        connection.close()
        raise
    return connection
