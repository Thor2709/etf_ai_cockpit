# INT-23 — Chunk store and lexical search

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P4`; gate `G4`; lane `E`; estimated size `medium`
- Logical prerequisites: `-`; source-file serialization: `-`
- Readiness: `READY`
- Intended files: `data/document_chunks.py; application/research_evidence.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Chunk store and lexical search
- Gate G4 | Priority P4 | Size medium | Depends on: none | Features: F0041, F0042, F0048, F0050
- Upstream: SQLite FTS5 (stdlib), `bm25()`.
- Targets: `data/document_chunks.py` (new), `application/research_evidence.py`, `data/pillar3_extract.py` (`:175-177`, `:237`), `parsers/etf_report.py` (`:442`, `:483-489`).
- Schema: `DocumentChunk(chunk_id, chunk_schema_version, chunker_version, document_sha256, source_id, published_at, known_at, revision_of, page, page_sha256, section, char_start, char_end, text_sha256, text)`. `chunk_id` = hash of `(document_sha256, page, char_start, char_end, chunker_version)`, so it is stable across re-indexing. A new chunker version adds rows; it does not rewrite old ones. A citation stores `chunk_id` and `document_sha256`; a citation that does not resolve fails closed.
- Acceptance: a hit returns page and character span; a document with `known_at` after `as_of` is not returned; re-indexing keeps existing `chunk_id` values.
