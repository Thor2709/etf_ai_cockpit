# INT-26 — LLM structured output, presets and report export

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P4`; gate `G4`; lane `E`; estimated size `small`
- Logical prerequisites: `INT-23`; source-file serialization: `INT-25 (application/research_evidence.py)`
- Readiness: `READY`
- Intended files: `audit/local_llm.py; application/research_report.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

LLM structured output, presets and report export
- Gate G4 | Priority P4 | Size small | Depends on: INT-23 | Features: F0159, F0160, F0173, F0210
- Targets: `audit/local_llm.py` (`:94`, `:222-239`, `:276`), `configs/local_llm.yaml`, `application/research_report.py` (new), `portfolio/review_reports.py` (`:93-94`).
- Steps: structured output per backend (LM Studio, Ollama and llama.cpp differ in how they accept a JSON schema); a per-preset capability flag; when a backend has no schema support the request falls back to the prompt plus the existing pydantic validation; Markdown and HTML report in which each number is rendered from a `Metric` key with its source ids and each claim has a `chunk_id` citation; LLM text is marked as commentary and has no numeric authority.
- Acceptance: a grounding check proves that every number in a generated report equals its metric and that every citation resolves; a non-conforming answer is rejected as today.
