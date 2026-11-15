# INT-18 — 8-K earnings releases and 10-K sections

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P3`; gate `G4`; lane `D`; estimated size `medium`
- Logical prerequisites: `INT-06, INT-17`; source-file serialization: `-`
- Readiness: `NEEDS_AUTHORITY (U1: extra not yet approved)`
- Intended files: `data/sec_filing_documents.py; data/earnings_surprise.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

8-K earnings releases and 10-K sections (EdgarTools)
- Gate G4 | Priority P3 | Size medium | Depends on: INT-06, INT-17 | Features: F0031, F0050, F0056
- Upstream (v6.1.0): `edgar/company_reports/current_report.py` (`CurrentReport`), `edgar/earnings.py` (`get_earnings_tables`, `find_earnings_exhibit`), `edgar/company_reports/ten_k.py` (`TenK.sections`), `edgar/storage/_local.py` (`use_local_storage(path, allow_network_fallback=False)`).
- Targets: `data/sec_filing_documents.py` (new), `data/earnings_surprise.py`, `data/event_calendar.py`.
- Steps: first a spike that proves the exact local-file API under socket denial; if it fails, stop. Then: Item 2.02 detection; EX-99.1 tables as unreviewed candidates; the release time printed in the document fills `public_announcement_time` only when it is explicit, otherwise it stays `unavailable`; risk-factor and MD&A sections as chunks for INT-23.
- Acceptance: with the network blocked a stored 8-K yields its items and one table; filing time and announcement time are separate fields.
