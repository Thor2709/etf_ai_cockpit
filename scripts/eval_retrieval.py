"""Evaluate lexical, dense and hybrid chunk retrieval on labelled questions (INT-25).

Questions are a JSON list of ``{"question": ..., "chunk_id": ...}`` where ``chunk_id`` is the chunk that
answers the question; a label must be checked against the chunk text when it is written (this script only
checks that it resolves). Fewer than
``MIN_QUESTIONS`` questions, a missing chunk store or a label that does not resolve gives
``insufficient_evidence``: no metrics are invented and hybrid stays disabled. ``hybrid_enabled`` is true
only when the three metrics of hybrid are all at least those of lexical search; it is the evidence for
setting ``document_embeddings.HYBRID_ENABLED``, which stays False in the code.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.data import document_chunks as chunk_store  # noqa: E402
from etf_cockpit.data import document_embeddings as embeddings  # noqa: E402
from etf_cockpit.data.local_storage import connect_local_database  # noqa: E402

MIN_QUESTIONS = 50
K = 10
MODES = ("lexical", "dense", "hybrid")


def metrics(rankings: Sequence[Sequence[str]], relevant: Sequence[str], k: int = K) -> dict[str, float]:
    """Recall@k, MRR and nDCG@k for one relevant chunk per question (binary relevance)."""

    ranks = [next((i for i, chunk_id in enumerate(ranking[:k], start=1) if chunk_id == answer), None)
             for ranking, answer in zip(rankings, relevant, strict=True)]
    n = len(ranks)
    return {
        f"recall@{k}": sum(rank is not None for rank in ranks) / n,
        "mrr": sum(1 / rank for rank in ranks if rank) / n,
        f"ndcg@{k}": sum(1 / math.log2(rank + 1) for rank in ranks if rank) / n,
    }


def hybrid_not_worse(lexical: Mapping[str, float], hybrid: Mapping[str, float]) -> bool:
    return all(hybrid[name] >= value for name, value in lexical.items())


def evaluate(root: Path, questions: Sequence[Mapping[str, Any]], *, as_of: str, k: int = K) -> dict[str, Any]:
    path = Path(root) / "data" / chunk_store.CHUNK_STORE_NAME
    report: dict[str, Any] = {
        "schema_version": "retrieval-eval.v1", "as_of": as_of, "k": k, "question_count": len(questions),
        "min_questions": MIN_QUESTIONS, "status": "insufficient_evidence", "reason": None,
        "modes": dict.fromkeys(MODES), "mode_unavailable": {}, "hybrid_enabled": False, "execution_allowed": False,
    }
    reason = _insufficient_reason(path, questions)
    if reason:
        return {**report, "reason": reason}
    texts = [str(item["question"]) for item in questions]
    answers = [str(item["chunk_id"]) for item in questions]
    searches = {
        "lexical": lambda query: chunk_store.search(path, query, as_of=as_of, limit=k),
        "dense": lambda query: embeddings.dense_search(path, query, as_of=as_of, limit=k),
        "hybrid": lambda query: embeddings.hybrid_search(path, query, as_of=as_of, limit=k),
    }
    if embeddings.embedding_status()["status"] == "available":
        embeddings.index_embeddings(path)
    for mode, search in searches.items():
        results = [search(query) for query in texts]
        bad = next((result for result in results if result["status"] != "available"), None)
        if bad is None:
            report["modes"][mode] = metrics([[hit["chunk_id"] for hit in result["hits"]] for result in results], answers, k)
        else:
            report["mode_unavailable"][mode] = bad["reason"]
    lexical, hybrid = report["modes"]["lexical"], report["modes"]["hybrid"]
    report["status"] = "ok" if lexical else "insufficient_evidence"
    report["reason"] = None if lexical else report["mode_unavailable"].get("lexical")
    report["hybrid_enabled"] = bool(lexical and hybrid and hybrid_not_worse(lexical, hybrid))
    return report


def _insufficient_reason(path: Path, questions: Sequence[Mapping[str, Any]]) -> str | None:
    if len(questions) < MIN_QUESTIONS:
        return f"{len(questions)} labelled questions; at least {MIN_QUESTIONS} are required"
    if not path.is_file():
        return "no document chunk store"
    with closing(connect_local_database(path)) as connection:
        known = {row[0] for row in connection.execute("SELECT chunk_id FROM chunks")}
    missing = sum(str(item.get("chunk_id")) not in known for item in questions)
    return f"{missing} labels do not resolve to a chunk in the store" if missing else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--questions", type=Path, default=None)
    parser.add_argument("--as-of", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    source = args.questions or root / "data" / "retrieval_eval" / "questions.json"
    try:
        questions = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        questions = []
    report = evaluate(root, questions if isinstance(questions, list) else [], as_of=args.as_of)
    output = args.output or root / "artifacts" / "retrieval_eval" / "latest" / "retrieval-eval.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"retrieval_eval_status={report['status']} hybrid_enabled={str(report['hybrid_enabled']).lower()} "
          f"questions={report['question_count']} reason={report['reason']}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
