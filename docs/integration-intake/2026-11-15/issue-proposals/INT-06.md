# INT-06 — Earnings surprise and filing reaction (analyst-free)

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P1`; gate `G1`; lane `D`; estimated size `medium`
- Logical prerequisites: `INT-02`; source-file serialization: `INT-03 (data/stock_sources.py)`
- Readiness: `READY`
- Intended files: `data/earnings_surprise.py; data/stock_sources.py; data/sec_pit_facts.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Earnings surprise and filing reaction (analyst-free)
- Gate G1 | Priority P1 | Size medium | Depends on: INT-02 | Features: F0031, F0056, F0106, F0017
- Upstream: none.
- Targets: `data/earnings_surprise.py` (new, bitemporal table), `data/sec_pit_facts.py` (acceptance-time gate `:57-72`), `data/stock_sources.py` (known-at `:659`, `:682`), `parsers/sec_submissions.py` (`acceptanceDateTime` `:287`), `data/event_calendar.py`.
- Two event times, never merged:
  - `sec_receipt_time`: acceptance time of the first SEC filing that contains the quarter figures (8-K Item 2.02, else 10-Q / 10-K). This is the only event time this issue has evidence for.
  - `public_announcement_time`: the actual release time. It can be earlier than the SEC receipt. It is `unavailable` here; INT-18 fills it when the release document gives it.
- Signals:
  - `sue_eps`, `sue_revenue`: `(x_q - x_{q-4}) / std(seasonal differences)`, using only quarters with `known_at` before this quarter's receipt, as originally reported, at least 6 and at most 8 seasonal differences, split-adjusted with adjustments known at that time. `available_at = sec_receipt_time` after the existing rule (after 17:30 ET counts as the next session).
  - `filing_reaction_3s`: VWCE-relative return over sessions `t-1` close to `t+1` close, where `t` is the first session that closes after `sec_receipt_time`. `event_definition = "sec_receipt"`. `available_at` = first session open after `t+1`. It is not named an earnings-announcement return, because the receipt can follow the announcement.
- Steps: use the acceptance-time rule in the runtime known-at path (today only `scripts/ingest_sp500.py` uses it); compute and store rows with `pit_grade = observed`; write receipt dates to the event calendar as SEC-receipt events; publish the three columns to the panel as a shadow component `earnings_information` (weight 0).
- Acceptance:
  - A decision at the close of `t` or `t+1` does not see `filing_reaction_3s`; a decision at the open after `t+1` does.
  - A quarter filed after the decision time is absent.
  - Fewer than 6 seasonal differences gives `unavailable`.
  - Non-US issuers give `unavailable`.
