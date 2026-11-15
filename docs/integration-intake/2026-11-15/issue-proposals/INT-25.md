# INT-25 — Embedding retrieval and reranking

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P4`; gate `G4`; lane `E`; estimated size `small`
- Logical prerequisites: `INT-01, INT-23`; source-file serialization: `-`
- Readiness: `NEEDS_AUTHORITY (U1: extra not yet approved)`
- Intended files: `data/document_embeddings.py; application/research_evidence.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Embedding retrieval and reranking (fastembed)
- Gate G4 | Priority P4 | Size small | Depends on: INT-01, INT-23 | Features: F0043, F0044, F0045, F0047, F0173
- Upstream: `qdrant/fastembed` v0.9.1 (Apache-2.0): `fastembed/text/text_embedding.py`, `fastembed/rerank/cross_encoder/onnx_text_cross_encoder.py`. Weights (each pinned by revision and hash, licence confirmed on the model page, ONNX conversion source recorded): `BAAI/bge-small-en-v1.5` (MIT), `BAAI/bge-reranker-v2-m3` (Apache-2.0), `Xenova/ms-marco-MiniLM-L-6-v2`.
- Targets: `data/document_embeddings.py` (new; vectors keyed by `chunk_id` with `index_version` and model revision), `application/research_evidence.py`, `scripts/eval_retrieval.py` (new).
- Evaluation: a labelled set of at least 50 questions over real filings in the store, with the answering `chunk_id`; report Recall@k, MRR and nDCG for lexical only, dense only and hybrid (reciprocal-rank fusion). Hybrid is enabled only if it is not worse than lexical on that set.
- Acceptance: the evaluation report exists with all three modes; with fastembed absent search is lexical; the socket-denial test passes.
