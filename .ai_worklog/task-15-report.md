# Task 15 - PRIIPs KID parser and index methodology importer

## RED

- Added focused parser edge-case coverage before production edits: missing SRI,
  malformed KID cost table, image-only/empty PDF, unsupported language, missing
  methodology version/date, unknown provider/index and retained holdings-conflict
  warnings.
- Added persistence and Instrument Detail provenance tests first. The first
  persistence run failed with the expected `ModuleNotFoundError` because the
  parsed-disclosure store did not exist yet.
- Baseline official fixture run failed before implementation because the runtime
  lacked the declared optional `pdfplumber` dependency (`ModuleNotFoundError`);
  the wrong-ISIN identity assertion consequently also failed before extraction.

## GREEN / fixes

- Extended both parser contracts to schema/parser version 2.0 with deterministic
  page-normalised extraction, source pages/checksums, confidence, warnings,
  document date/version, explicit missing/manual-review states and conservative
  score eligibility.
- PRIIPs extraction now covers product, ISIN, manufacturer, SRI, holding period,
  scenarios and cost-table fields. Methodology extraction covers provider/index,
  version/date, eligibility, weighting, review/rebalance and caps.
- Added atomic, idempotent checksum-keyed stores for parsed KID and methodology
  rows, including parser warnings/source pages, authority/freshness, schema
  version and unavailable rows.
- Registered parsed imports through the existing FundDocument registry and
  surfaced parsed fields/provenance in ETF Disclosures and Instrument Detail.
  Audit export now includes both parsed stores.
- Missing, malformed, unsupported-language, unknown-provider/index and conflict
  evidence remains visible and score-ineligible; no holdings/prospectus or
  execution boundary was changed.

## Evidence

- With `pdfplumber` installed from the already-declared `requirements-parsers.txt`,
  official Vanguard KID and FTSE GEIS fixtures pass and return the expected
  ISIN/date/SRI/holding/version/source pages/checksums.
- Edge-case parser, persistence, registry, Instrument Detail, UI contract and
  audit-export checks pass.

## Commands

- `python -m pytest -q tests/test_priips_kid_parser.py tests/test_index_methodology_parser.py tests/test_parsed_disclosures.py tests/test_instrument_detail.py tests/test_fund_documents.py tests/test_button_contracts.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered --disable-warnings --maxfail=1` - passed.
- `python -m pytest -q tests/test_trust_critical_artifacts.py::test_audit_export_includes_trust_critical_evidence_and_session_log --disable-warnings --maxfail=1` - passed.
- `python -m ruff check` on all Task 15 source/tests - passed.
- `python -m compileall -q src tests` - passed.
- `git diff --check` - passed (only normal Git line-ending notices).

## Limitations / review

- Full clean-first-run, package rebuild and browser/computer-use gates remain
  later release checks. Runtime dependency absence was recorded separately above;
  the environment now has the declared parser dependency for fixture verification.
- Parsed KID/methodology records expose source-aware eligibility metadata but do
  not alter approved scoring weights or authority boundaries. Methodology-versus-
  holdings disagreement is retained as parser/manual-review evidence and remains
  non-executable.
