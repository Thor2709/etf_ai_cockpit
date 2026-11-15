# INT-17 — SEC insider and 13F evidence

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `D`; estimated size `medium`
- Logical prerequisites: `INT-01`; source-file serialization: `-`
- Readiness: `NEEDS_AUTHORITY (U1: extra not yet approved)`
- Intended files: `data/sec_ownership.py; data/sec_edgar_provider.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

SEC insider and 13F evidence (EdgarTools parsers)
- Gate G3 | Priority P2 | Size medium | Depends on: INT-01 | Features: F0018, F0019, F0167
- Upstream: `dgunning/edgartools` v6.1.0 (`c7ae63b5`, MIT): `edgar/ownership/forms.py` (`Ownership.from_xml` / `parse_xml`, `Form3`, `Form4`, `Form5`, `to_dataframe`), `edgar/ownership/summary.py`, `edgar/ownership/core.py` (`detect_10b5_1_plan`), `edgar/thirteenf/parsers/infotable_xml.py`.
- Targets: `data/sec_ownership.py` (new), `data/sec_edgar_provider.py` (new method `fetch_filing_document` beside `fetch_submissions:203`), `parsers/sec_submissions.py` (`:279-310`).
- Steps: the Cockpit fetches the XML; the parser runs on bytes, under the socket-denial test.
  - Form 3/4/5: store the transaction code and classify: `P` open-market purchase and `S` open-market sale count for signals; `A` grant, `M` exercise, `F` tax withholding, `G` gift and derivative rows are stored but excluded; `is_10b5_1` flag excludes planned trades. `known_at` = acceptance time.
  - 13F: a 13F is a delayed report (due up to 45 days after quarter end). Store `period_end`, `known_at` = acceptance time, the amendment chain (`13F-HR/A` supersedes by accession, both kept), and a flag for incomplete reporting (confidential treatment). Holdings are positions at `period_end` known at `known_at`; they are never labelled current exposure.
  - Features (shadow): net open-market purchases by officers and directors over 90 days; cluster buys; quarter-on-quarter holder and share change by `known_at`.
- Acceptance: fixture XML parses without network; a grant is not counted as a purchase; a filing accepted after the decision time is not used; an amendment replaces the original from its own acceptance time only.
