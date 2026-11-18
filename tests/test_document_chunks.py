from __future__ import annotations

from etf_cockpit.application.research_evidence import search_document_chunks
from etf_cockpit.data import document_chunks as store

PAGES = ["Cover page.", "The fund's ongoing charges were 0.22 percent in 2025."]


def _index(root, *, sha: str, known_at: str, chunker_version: str = store.CHUNKER_VERSION) -> list[store.DocumentChunk]:
    chunks = store.chunk_pages(PAGES, document_sha256=sha, source_id="annual-report", published_at="2026-03-01T00:00:00Z",
                               known_at=known_at, chunker_version=chunker_version)
    store.index_document(root / "data" / store.CHUNK_STORE_NAME, chunks)
    return chunks


def test_a_hit_returns_page_and_span_and_a_later_document_is_not_returned(tmp_path) -> None:
    _index(tmp_path, sha="a" * 64, known_at="2026-03-02T00:00:00Z")
    _index(tmp_path, sha="b" * 64, known_at="2026-06-01T00:00:00Z")

    result = search_document_chunks(tmp_path, "ongoing charges", as_of="2026-04-01T00:00:00Z")

    assert result["status"] == "available"
    [hit] = result["hits"]
    assert (hit["document_sha256"], hit["page"]) == ("a" * 64, 2)
    assert PAGES[1][hit["char_start"]:hit["char_end"]] == hit["text"]


def test_reindex_keeps_ids_a_new_chunker_adds_rows_and_a_bad_citation_fails_closed(tmp_path) -> None:
    first = _index(tmp_path, sha="a" * 64, known_at="2026-03-02T00:00:00Z")
    again = _index(tmp_path, sha="a" * 64, known_at="2026-03-02T00:00:00Z")
    newer = _index(tmp_path, sha="a" * 64, known_at="2026-03-02T00:00:00Z", chunker_version="pages-v2")
    path = tmp_path / "data" / store.CHUNK_STORE_NAME

    assert [chunk.chunk_id for chunk in again] == [chunk.chunk_id for chunk in first]
    assert {chunk.chunk_id for chunk in newer}.isdisjoint(chunk.chunk_id for chunk in first)
    assert store.resolve(path, first[1].chunk_id, "a" * 64) == first[1]
    assert store.resolve(path, newer[1].chunk_id, "a" * 64) == newer[1]
    assert store.resolve(path, first[1].chunk_id, "c" * 64) is None
