# ADR-0009 — Forward nightly paper path

**Status:** proposed

**Date:** 2026-11-20

## Context

The forward paper path (INT-15A/B, readiness, recorder, execution) was built and
tested on fixtures, never against real nightly timing and real data. The
activation review found 7 breaks:

1. The refresh blocks on `stale_data` for no-bar and carried-forward symbols.
2. Prices have no per-bar stamps; batch snapshot metadata cannot give per-bar knowledge or action evidence.
3. Readiness reads the backfill score run and the bots read the live publication: two scorings, so the hash check can never pass.
4. The driver gates the last VWCE session before the UTC run day; the recorder gates the run day itself.
5. No stock has `listing:*` membership; licensed S&P history is incomplete.
6. There are no `challenger_engines`; B2-o takes raw listing-currency prices; B1-r needs observed snapshots, features and EUR adjusted inputs.
7. A missing challenger makes the run `partial`, which the driver rejects; the driver has no paper-enable check.

Break 1 is the refresh-tolerance part of PR-1 and is out of scope for this record.

A second review left 8 open items: (1) one-night membership lag, (2) fill
price known at the fill time, (3) `current_price` and `instrument_currency` in
backfill rows, (4) versioning of adjusted values and corporate actions,
(5) history-stamp recovery, (6) S&P 500 bindings, (7) index-coverage census
selection, (8) B1-r observed feature vintages. The per-bar stamp rule was also
open.

Preconditions found (report only; no change in this record):

| # | Finding |
|---|---|
| P1 | 3497 of 3932 work2 instruments have stored price `currency` EUR but a non-EUR configured currency; `eur_basis_prices` marks each conflict unavailable. |
| P2 | The existing S&P binding rule binds 469 of 503 members (93.2%) < 0.95; with "verified, unique exact ticker, USD" it binds 499/503 (99.2%). |
| P3 | Two price writers: `commit_price_import` and `universe_fetch.promote_staging`. |
| P4 | The nightly job runs 2.5-3.5 h; bars of session D are often stamped after 00:00 UTC on D+1. |
| P5 | `score_as_of` sets `created_at` to the session end 23:59:59 UTC, not the real run time. |
| P6 | work2 prices have no `known_at`; 27,353 rows have null stamps; `PriceBook.from_root` needs `known_at`. |
| P7 | `controls.paper.enabled: false` exists; the driver never reads it. |
| P8 | work2 `score_history_backfill.parquet` has 0 rows. |

## Decision

Adopt the design in [forward-paper-path.md](../forward-paper-path.md)
(**TARGET / PLANNED**). The paper stages run before tonight's refresh, on the
data that the previous night's refresh committed. Order: capture → forward
score run(S) → readiness(S) → recorder → execution → AI account → refresh →
live rescore → publish (UI only). Invariants stay: `execution_allowed=false`,
no zero-fill, no look-ahead, no survivorship leakage, gates override models.

Items settled:

- Stamp rule: option (b), contract C1.
- Item 1: option (c), accept the one-night lag; capture is the first step and the paper stages run before the refresh.
- Item 2: option (a), session-opens day job and `fill_time_utc` "15:20" (design review moved it from "15:00"); the `price_not_known_at_fill_time` gate stays strict (C7).
- Item 3: option (a), add `current_price` and `instrument_currency` to `_BASE_HISTORY_EXTRA`; both enter `snapshot_hash`.
- Item 4: option (b), compare raw values by value and `adjusted_close` by its one-session return; `adjusted_close` levels are not PIT evidence.
- Item 5: option (b), no snapshot-chain walk; one-time migration `known_at := ingested_at`; option (c) only on a later request.
- Item 6: option (b), bind at capture time from tonight's page and the universe store with the widened identity rule.
- Item 7: option (a), one-day census intervals, at most one capture per scope per UTC day; the reader fails when the census is absent or empty.
- Item 8: option (a), the forward run writes its feature frame as a vintage once per session (C9).

Contracts (one bullet each; full text in the design document):

- **C1 Price stamps:** one `stamp_price_availability` function in `data/import_pipeline.py`, called by both writers and by rollback; `known_at` is never earlier than retrieval; revisions by raw value or one-session adjusted return; one-time migration from `ingested_at`.
- **C2 Nightly S&P capture:** fetch the constituents page with `core.http_fetch.get_checked`, parse and bind with the moved `constituents()` and `select_instrument_bindings` in `data/sp500_capture.py`, guard 480-520 rows, record one `listing:sp500:all` capture per UTC day; the skip key is census presence, and a capture without its census gets the census rebuilt from the stored raw payload.
- **C3 Index-coverage census:** append-only one-day rows per page member; for a scope with a `source_kind='self'` capture, `_index_coverage_check` fails on a missing census or 0 members; licensed-only scopes behave as before; threshold 0.95 unchanged.
- **C4 Forward score run:** `backfill_score_history(..., completed_at=t_S)` stamps `created_at` = t_S, `provenance` = `forward_nightly`, raises on a consumed price row with `known_at` > t_S, does not admit an instrument with a null-stamped consumed row (`price_unstamped`), and reuses an existing forward run for S. `load_backfill_score_history` gets a provenance set: readiness, the recorder and the writer merge read both provenances; historical replay readers exclude forward rows; eligibility rows get the same `provenance` filter and the manifest lists the stored provenances.
- **C5 Readiness and recorder binding:** the recorder reads the same backfill store and run as readiness (not the live publication), gates on S, uses the month of S as slot month, and takes candidates only from snapshot H. Replaced checks: the publication binding becomes the recomputed content hash of the stored forward rows without `config_fingerprint` (= H); the publication-hash comparison in the driver becomes `PaperBotRunResult.candidate_snapshot == H`.
- **C6 Challengers:** B2-o uses stamped adjusted rows through `eur_basis_prices`; B1-r uses `build_pit_panel` with t_S decision times and C9 features; both record `NO_NEW_TRADE` when unavailable.
- **C7 Session opens and fills:** an append-only `session_opens.parquet` with real retrieval `known_at`, written by a job that does not wait on the data-jobs mutex; the observation is the one canonical open for fills, the legacy fill-basis check, the B0 shadow and its valuation re-check; fills use only an observation known at or before `fill_time_utc` "15:20"; a miss (also `split_on_fill_session`, per order) is terminal.
- **C8 Driver and status:** `controls.paper.enabled` false, a readiness FAIL or no new session (`no_new_session`) skips recorder and execution; the refresh runs whatever the paper stages do, and a paper-stage failure keeps a non-zero exit code; `--dry-run` leaves the scheduled command; `partial` is accepted only in a bounded case (a bounded relaxation).
- **C9 Feature vintages:** `data/derived/feature_vintages/<S>.parquet` is written once from `FeatureService.compute_features(publish=False)` with `known_at` = `available_at` = t_S.

Owner decisions (decided 2026-11-20):

| # | Decision | Outcome |
|---|---|---|
| O1 | Fill clock | 2a: opening-price day job (15:45 local) and `fill_time_utc` "15:20" (design review moved it from "15:00"; still before the 15:30 UTC Xetra close in CEST); the `price_not_known_at_fill_time` gate is kept. |
| O2 | S&P identity rule | Accepted: a verified-ISIN stock with a non-US ISIN binds when its configured currency is USD and the suffix-free ticker is unique (the currency is configured metadata, not provider-verified; see P1). |
| O3 | Scheduled task `ETF-Cockpit-Session-Opens` (Mon-Fri 15:45 local, 1 h limit) | Register after the code PRs merge; remove `--dry-run` only when `controls.paper.enabled` is set. |
| O4 | One-night lag | Accepted. |
| O5 | Capture row-count guard | Accepted: 480-520 rows. |
| O6 | Currency-label defect P1 | Fix before go-live, as a separate task (precondition). |
| O7 | Stage order | Accepted: paper stages before tonight's refresh. |

## Consequences

- New stores: `data/derived/feature_vintages/<session>.parquet` and `data/validated/prices/session_opens.parquet`; new census rows in `index_coverage.parquet` and nightly captures in `membership.sqlite`.
- New scheduled task `ETF-Cockpit-Session-Opens`; the owner registers it (O3). `register_scheduled_refresh.ps1` gets the third job and skips a task that already exists. The task does not wait on the `Global\ETF-Cockpit-Data-Jobs` mutex; it has a bounded start check instead.
- The monthly slot month becomes the month of S; nights with no new session (weekends, holidays) skip the paper stages with `no_new_session`.
- `scripts/ingest_sp500.py` must not run on the forward root.
- Preconditions before go-live: fix P1 (O6); the first night after go-live fails readiness (no prior census).
- Accepted limitations: two-session data lag; B1-r records `NO_NEW_TRADE` for about 2 years after the first capture; only S&P 500 stocks and observed-trading ETFs are bot-eligible; Asian listings fill at their open with a 15:20 UTC clock after their close; a late or failed opens job loses that fill (terminal miss); a provider change of `adjusted_close` that keeps every one-session return is not detected.

## Alternatives

- Stamp rule: (a) the earlier table as written (batch time can be earlier than the download; rollback bypasses the rule); (c) a full bitemporal price store per vintage (large).
- Item 1: (a) accept the lag without the capture-first order; (b) decide session D on night D (separates session date and observation cut-off in many contracts).
- Item 2: (b) relax the check to "bar known by the execution run" (weakens a fail-closed gate); (c) evening `fill_time_utc` "23:30" (fails on most nights, P4).
- Item 3: (b) join the live board at record time (mixes two scorings); (c) recompute price evidence in the recorder (second calculation path).
- Item 4: (a) compare levels of every consumed value (every distribution re-stamps the full history); (c) derive adjusted series at each cut-off (new canonical path, changes every consumer).
- Item 5: (a) walk the snapshot chain (complex; batch times are not proof); (c) a later chain recovery from checksum-verified records only.
- Item 6: (a) run the full `acquire_sp500` generator nightly (needs history inputs and SEC fetches); (c) keep the US-ISIN filter (93.2%, readiness fails every night).
- Item 7: (b) a `capture_id` column (breaks the 9-column schema check of `ingest_sp500`); (c) long intervals in the sidecar (duplicate ledger path).
- Item 8: (b) recompute features at each past cut-off (fails for non-price inputs); (c) defer (every night adds a night to the preflight).

## Evidence and links

[Forward nightly paper path](../forward-paper-path.md),
[ADR-0003](ADR-0003-point-in-time-evidence.md),
[Local paper trading](../paper-trading.md).
Code: `src/etf_cockpit/application/daily_paper.py`,
`src/etf_cockpit/application/score_backfill.py`,
`src/etf_cockpit/portfolio/paper_bots.py`,
`src/etf_cockpit/portfolio/paper_bots_readiness.py`,
`src/etf_cockpit/portfolio/paper_bots_execution.py`,
`src/etf_cockpit/portfolio/paper_trading.py`,
`src/etf_cockpit/data/score_history_backfill.py`,
`src/etf_cockpit/data/import_pipeline.py`,
`src/etf_cockpit/application/universe_fetch.py`,
`src/etf_cockpit/data/universe_membership.py`,
`scripts/acquire_sp500.py`, `scripts/scheduled_refresh.ps1`.
Config: `configs/paper_bots_v1.yaml`, `configs/paper_bots_execution_v1.yaml`,
`configs/data_readiness_v1.yaml`, `configs/sp500_universe_v1.yaml`.
