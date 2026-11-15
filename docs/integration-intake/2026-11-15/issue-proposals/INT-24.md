# INT-24 — Docling document worker

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P4`; gate `G4`; lane `E`; estimated size `medium`
- Logical prerequisites: `INT-01, INT-23`; source-file serialization: `-`
- Readiness: `NEEDS_AUTHORITY (U1: extra not yet approved)`
- Intended files: `application/docling_worker.py; application/document_parsers.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Docling document worker
- Gate G4 | Priority P4 | Size medium | Depends on: INT-01, INT-23 | Features: F0025, F0039, F0040, F0063
- Upstream: `docling-project/docling@a7760abf` (v2.150.0, MIT): `docling/document_converter.py`, `docling/datamodel/pipeline_options.py` (`PdfPipelineOptions`, `TableStructureOptions`, `RapidOcrOptions`), `docling/chunking/__init__.py` (`HybridChunker`).
- Targets: `application/docling_worker.py` (new, child process as in `parsers/esef_ixbrl.py:573`), `application/document_parsers.py`, `data/pillar3_queue.py` (`merge_extraction:101`), `core/resource_profiles.py` (limits).
- Preconditions from INT-01: every layout, table and OCR weight file is pinned with hash and confirmed licence; unconfirmed weights keep the feature disabled.
- Steps: child process with a time limit and a memory limit from the resource profile; offline switches set; diagnostic status (`unavailable`, `timeout`, `memory_limit`, `ok`); tables go to the review queue as unreviewed evidence; OCR only for pages without a text layer; pdfplumber stays the default.
- Acceptance: with docling absent the parsers behave as today; the worker passes the socket-denial test; a timeout gives a clean status; a fixture table reaches the review queue with page provenance.
