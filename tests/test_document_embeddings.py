from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

import pytest

from etf_cockpit.application.research_evidence import search_document_chunks
from etf_cockpit.data import document_chunks as store
from etf_cockpit.data import document_embeddings as emb
from etf_cockpit.plugins.registry import _network_probe
from scripts import eval_retrieval

AS_OF = "2026-04-01T00:00:00Z"
PAGES = [
    "The fund's ongoing charges were 0.22 percent in 2025.",
    "The index tracks large companies listed in developed markets.",
    "Sustainability risks are screened against the exclusion policy of the manager.",
]
MODEL_DIR = Path(os.environ.get("ETF_COCKPIT_TEST_EMBEDDING_MODEL_DIR", emb.EMBEDDING_MODEL_DIR))
LATER = {"known_at": "2026-06-01T00:00:00Z", "document_sha256": "b" * 64}


def _index(root: Path, pages=PAGES, *, known_at="2026-03-02T00:00:00Z", document_sha256="a" * 64) -> list[store.DocumentChunk]:
    chunks = store.chunk_pages(pages, document_sha256=document_sha256, source_id="annual-report", published_at="2026-03-01T00:00:00Z",
                               known_at=known_at)
    store.index_document(root / "data" / store.CHUNK_STORE_NAME, chunks)
    return chunks


def test_without_embeddings_search_is_lexical_hybrid_is_off_and_reranking_is_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(emb, "EMBEDDING_MODEL_DIR", tmp_path / "no-model")
    chunks = _index(tmp_path)

    result = search_document_chunks(tmp_path, "ongoing charges", as_of=AS_OF, mode="hybrid")
    dense = emb.dense_search(tmp_path / "data" / store.CHUNK_STORE_NAME, "ongoing charges", as_of=AS_OF)

    assert emb.HYBRID_ENABLED is False
    assert (result["status"], result["mode_used"], result["hits"][0]["chunk_id"]) == ("available", "lexical", chunks[0].chunk_id)
    assert "disabled" in result["fallback_reason"]
    assert dense["status"] == "unavailable" and dense["hits"] == []
    assert emb.rerank_status()["status"] == "unavailable"


def test_a_model_file_that_differs_from_its_pinned_hash_or_has_no_pin_is_unavailable(tmp_path, monkeypatch) -> None:
    emb._weight_rows.cache_clear()
    monkeypatch.chdir(tmp_path)  # the pins come from the repository registry, not the working directory
    for name in emb.pinned_files():
        (tmp_path / name).write_bytes(b"tampered")
    monkeypatch.setattr(emb, "EMBEDDING_MODEL_DIR", tmp_path)

    tampered = emb.embedding_status()
    monkeypatch.setattr(emb, "_weight_rows", lambda: ())
    unpinned = emb.embedding_status()

    assert tampered["status"] == "unavailable" and "does not match its pinned sha256" in str(tampered["reason"])
    assert unpinned["status"] == "unavailable" and "no sha256 pins" in str(unpinned["reason"])

    other = tmp_path / "other"
    other.mkdir()
    (other / "tokenizer.json").write_bytes(b"x")
    (other / "model_optimized.onnx").write_bytes(b"unpinned weights")  # a file fastembed loads, with no pin
    monkeypatch.setattr(emb, "EMBEDDING_MODEL_DIR", other)
    monkeypatch.setattr(emb, "_weight_rows", lambda: ({"file": "tokenizer.json", "sha256": hashlib.sha256(b"x").hexdigest()},))
    partial = emb.embedding_status()

    assert partial["status"] == "unavailable" and "not pinned" in str(partial["reason"])


def test_reciprocal_rank_fusion_metrics_and_the_hybrid_decision() -> None:
    assert emb.reciprocal_rank_fusion([["a", "b", "c"], ["c", "a", "d"]]) == ["a", "c", "b", "d"]
    limits = []
    side = lambda *_args, **kwargs: limits.append(kwargs["limit"]) or {"status": "available", "reason": None, "hits": []}  # noqa: E731
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(emb, "dense_search", side)
        patch.setattr(store, "search", side)
        emb.hybrid_search(Path("unused"), "q", as_of=AS_OF, limit=80)
    assert limits == [80, 80]  # a limit above the default candidate window is not capped

    rankings, relevant = [["a", "x"], ["x", "a"], ["x", "y"]], ["a", "a", "a"]
    result = eval_retrieval.metrics(rankings, relevant, k=2)
    assert result["recall@2"] == pytest.approx(2 / 3)
    assert result["mrr"] == pytest.approx(0.5)
    assert result["ndcg@2"] == pytest.approx((1 + 1 / math.log2(3)) / 3)

    assert eval_retrieval.hybrid_not_worse({"recall@5": 0.8, "mrr": 0.6, "ndcg@5": 0.7}, {"recall@5": 0.8, "mrr": 0.7, "ndcg@5": 0.7})
    assert not eval_retrieval.hybrid_not_worse({"recall@5": 0.8, "mrr": 0.6, "ndcg@5": 0.7}, {"recall@5": 0.7, "mrr": 0.7, "ndcg@5": 0.7})


def test_too_few_questions_or_an_unresolved_label_is_insufficient_evidence_and_keeps_hybrid_off(tmp_path) -> None:
    chunks = _index(tmp_path)
    few = [{"question": "ongoing charges", "chunk_id": chunks[0].chunk_id}] * 3
    unresolved = [{"question": f"q{n}", "chunk_id": "0" * 64} for n in range(50)]
    future = _index(tmp_path, [f"Page {n} marker zq{n}x." for n in range(50)], **LATER)  # first known after as_of
    future_only = [{"question": f"zq{n}x", "chunk_id": chunk.chunk_id} for n, chunk in enumerate(future)]

    for questions in (few, unresolved, future_only):
        report = eval_retrieval.evaluate(tmp_path, questions, as_of=AS_OF)
        assert report["status"] == "insufficient_evidence" and report["hybrid_enabled"] is False
        assert set(report["modes"]) == {"lexical", "dense", "hybrid"} and report["modes"]["lexical"] is None


def test_fifty_labelled_questions_give_lexical_metrics_and_dense_hybrid_stay_off_without_embeddings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(emb, "EMBEDDING_MODEL_DIR", tmp_path / "no-model")
    pages = [f"Section {n} covers the marker word zq{n}x in detail." for n in range(50)]
    chunks = _index(tmp_path, pages)
    questions = [{"question": f"zq{n}x", "chunk_id": chunk.chunk_id} for n, chunk in enumerate(chunks)]

    report = eval_retrieval.evaluate(tmp_path, questions, as_of=AS_OF)

    assert report["status"] == "ok" and report["question_count"] == 50
    assert report["modes"]["lexical"]["mrr"] == 1.0
    assert report["modes"]["dense"] is None and report["modes"]["hybrid"] is None
    assert report["hybrid_enabled"] is False


def test_dense_retrieval_runs_offline_from_the_pinned_local_model(tmp_path, monkeypatch) -> None:
    pytest.importorskip("fastembed")
    if not (MODEL_DIR / "model_optimized.onnx").is_file():
        pytest.skip("pinned embedding weights are not present")
    monkeypatch.setattr(emb, "EMBEDDING_MODEL_DIR", MODEL_DIR)
    chunks = _index(tmp_path)
    path = tmp_path / "data" / store.CHUNK_STORE_NAME
    query = "what does it cost each year to hold the fund"
    assert emb.embedding_status()["status"] == "available"  # first import and hash check happen outside the probe

    with _network_probe() as calls:
        assert emb.dense_search(path, query, as_of=AS_OF)["status"] == "unavailable"  # nothing embedded yet
        assert emb.index_embeddings(path) == 3
        assert emb.index_embeddings(path) == 0  # vectors are keyed by chunk id, index version and model revision
        _index(tmp_path, ["The fund holds no securities lending positions."], **LATER)  # known after as_of: not counted, not returned
        dense = emb.dense_search(path, query, as_of=AS_OF)
        hybrid = emb.hybrid_search(path, query, as_of=AS_OF)
        _index(tmp_path, ["A chunk added after the last embedding run."], known_at="2026-03-03T00:00:00Z", document_sha256="c" * 64)
        gap = emb.dense_search(path, query, as_of=AS_OF)

    assert calls == [] and os.environ["HF_HUB_OFFLINE"] == "1"
    assert dense["hits"][0]["chunk_id"] == chunks[0].chunk_id and len(dense["hits"]) == 3
    assert hybrid["hits"][0]["chunk_id"] == chunks[0].chunk_id
    assert gap["status"] == "unavailable" and "no embedding" in str(gap["reason"])
