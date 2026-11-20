# Forward nightly paper path

**State:** every contract in this document is **TARGET / PLANNED**. Nothing here
is VERIFIED CURRENT. Decision record: [ADR-0009](decisions/ADR-0009-forward-paper-path.md).
References P1-P8 (preconditions), "item 1-8" (settled design items) and O1-O7
(owner decisions) are defined in ADR-0009.

Invariants: `execution_allowed=false`, no zero-fill, no look-ahead, no
survivorship leakage, point-in-time evidence, risk and data-quality gates
override models, one canonical path per calculation.

## 1. Purpose

One nightly local run turns the newest completed session into at most one paper decision per bot per month,
and fills it at the next session open with a price known at the fill time. Paper only; `execution_allowed=false`.

## 2. Stores, writers and readers

| Store | Writer (only) | Readers |
|---|---|---|
| `data/validated/prices/prices_daily.parquet`, `data/clean/prices.parquet` | `stamp_price_availability` via `commit_price_import`, `promote_staging`, `rollback_latest_price_import` | score run, readiness, PriceBook, optimiser, panel |
| `data/derived/universe_membership/membership.sqlite` (scope `listing:sp500:all`) | nightly capture via `record_listing_capture` | `ListingHistory`, panel `membership_frame` |
| `data/derived/universe_membership/index_coverage.parquet` (scope `listing:sp500:all`) | nightly capture census writer | readiness `index_coverage` |
| `score_history_backfill*.parquet` (backfill store) | forward score run (`backfill_score_history`) | readiness, recorder |
| `data/derived/feature_vintages/<session>.parquet` (new) | forward score run | B1-r panel |
| `data/validated/prices/session_opens.parquet` (new) | session-opens job | execution fills |
| decision records, paper ledgers | recorder, execution (unchanged) | reports, opens job (read only) |

Rule: `scripts/ingest_sp500.py` must not run on the forward root. Its scope replacement would delete the census rows,
and readiness then fails closed.

## 3. Timing (UTC; winter shown; local = CET)

```text
Night D (job 21:30 UTC = 22:30 CET); all paper stages hold the cross-process writer guard
 21:30  a. S&P capture: fetch page -> bind -> ledger capture (snapshot_date=D, known_at~21:31)
           -> census rows [D, D+1)          (failure: logged; tomorrow's readiness fails)
 ~21:32 b. t_S = clock. Forward score run, S = latest VWCE session < D and <= stored data (= D-1)
           inputs: prices committed by night D-1's refresh (guard: every known_at <= t_S),
           membership/FX known by S 23:59:59 (census of night D-1)
           run_completed_at = t_S; feature vintage <S>.parquet (known_at = t_S)
        c. readiness(S) on run H (8 checks)            -> FAIL: skip d-f
        d. paper enabled? no -> skip e-f (like --dry-run)
        e. recorder(as_of = clock, decision_session = S, snapshot = H)
           -> decision decided_at = t_d (date d = UTC date of t_d); driver checks recorded snapshot == H
        f. execution: fill intents for sessions F with d < F < as_of.date(); AI account
 ~21:45 g. refresh prices + FX (2.5-3.5 h)  -> stamps (C1); bars of D for tomorrow's S = D
        h. live rescore + publish (UI only)
Day F (first VWCE session after d)
 13:30/14:30 US open; 07:00/08:00 Xetra open
 14:45 (13:45 CEST)  session-opens job: observe open of target + held instruments
                     -> session_opens rows (known_at = retrieval time)
 15:00  fill_time_utc: fill price = observed open with known_at <= 15:00
Night after F: step f books the fill at F 15:00 with that price.
```

Lag summary: data of session S → decision on night S+1 → fill at the open of the first session after the
decision date → booked one night later. The first night after go-live fails readiness (no prior census).

## 4. Contracts

**C1 Price stamps.** There is one function, `stamp_price_availability(stored, incoming, *, retrieved_at)`, in
`data/import_pipeline.py`. `commit_price_import` (before its checksum), `universe_fetch.promote_staging` (before
its write) and `rollback_latest_price_import` (stored = current, incoming = restored, `retrieved_at` = rollback time)
call it. The key is (`etf_id`, `date`). Fields:

| Field | Meaning | New row | Revised row | Unchanged row |
|---|---|---|---|---|
| `ingested_at` | when the current values entered the store | `retrieved_at` | `retrieved_at` | kept |
| `known_at` | system knowledge (= `ingested_at`) | `retrieved_at` | `retrieved_at` | kept |
| `available_at` | market availability | min(date 23:59:59 UTC, `retrieved_at`) | `retrieved_at` | kept |
| `actions_evidenced` | True only if the download asked for actions and returned per-row dividends and splits | from download | from download | kept |

No `availability_basis` column for prices: no price reader exists (it stays an FX field).

- `retrieved_at` is never earlier than the moment the values were in hand. Use the commit time, or the per-download return time when the writer has it.
- Revised = any of these differ: `open`, `high`, `low`, `close`, `volume`, `currency`, `is_adjusted`, `dividends`, `stock_splits`, `capital_gains` by value (NaN ≠ number); or the one-session return of `adjusted_close` differs by more than rel. 1e-6, where both rows have a previous session of the same instrument.
- Unchanged rows take the incoming values and keep their stamps (uniform re-base).
- Migration (runs once, idempotent): a row with `ingested_at` and no `known_at` gets `known_at := ingested_at`, and keeps `available_at`. A row with no stamps stays null and is unavailable to every stamped reader.
- Rule: `adjusted_close` levels are not PIT evidence. Readers use only ratios of `adjusted_close` within one vintage.

**C2 Nightly S&P capture.** Step a of the job, before the paper stages and the refresh.
- Fetch `https://en.wikipedia.org/wiki/List_of_S%26P_500_companies` with `core.http_fetch.get_checked(allowed=same_host_https(url), ...)` (`core/http_fetch.py:21-35,77-88`). Do not use the script's own urllib client.
- Parse with the existing `constituents()`, moved with `select_instrument_bindings` into `src/etf_cockpit/data/sp500_capture.py`; `scripts/acquire_sp500.py` imports both (one path).
- Guards: the header check (existing), and 480 ≤ rows ≤ 520 (O5). A guard failure means no capture.
- If the ledger already has a capture for (`listing:sp500:all`, today's UTC date), keep it and skip. This allows at most one capture per scope per day.
- `record_listing_capture(rows=[{"instrument_id": id} for bound], source="wikipedia:sp500_constituents", scope="listing:sp500:all", known_at=<retrieval time>, raw_payload=<page bytes>, snapshot_date=<UTC date of known_at>)`.
- Binding (item 6, O2 accepted): page row → exactly one universe-store record with `asset_type` stock, `isin_status` verified, configured `currency` USD, ticker = `sec_ticker(page ticker)` (Yahoo ticker without exchange suffix). Otherwise the row is unbound with a reason: `ambiguous_universe_records`, `no_verified_usd_stock`. The old US-ISIN filter gives 93.2% coverage, and readiness then fails (P2).

**C3 Index-coverage census.**
- Writer: after a recorded capture, append one row per page member: `scope`, `source_ticker`, `instrument_id` (null if unbound), `valid_from` = snapshot date, `valid_to` = snapshot date + 1 day, `member_known_at` = capture `known_at`, `identity_known_at` = capture `known_at` (null if unbound), `binding_status` `bound`/`unbound`, `reason`.
- The write is an atomic replace of the whole file with old rows + new rows. Rows are never deleted. If rows exist for (scope, `valid_from`), the writer skips.
- Reader changes in `_index_coverage_check`:
  1. A ledger index scope with no active row for the day → FAIL `unavailable: no visible census for <scope> on <day>`.
  2. Members = 0 for such a scope → FAIL.
- Unchanged: threshold 0.95, duplicate-row FAIL, unbound counted against coverage.

**C4 Forward score run.**
- `backfill_score_history(root, start=S, end=S, every=1, force=<reuse rule>, completed_at=t_S)` passes `completed_at` to `score_as_of`.
- When `completed_at` is given: `created_at` = `completed_at`, and it must be ≥ S 23:59:59 UTC, else raise. `provenance` = `forward_nightly`.
- Price guard (forward mode only): raise if any consumed price row lacks `known_at` or has `known_at` > t_S. The driver reads t_S while it holds the cross-process writer guard, so no write can come between the clock read and the score run.
- The membership, FX and feature `known_by` stay S 23:59:59.
- New run fields: `current_price`, `instrument_currency` (via `_BASE_HISTORY_EXTRA`); both are in `snapshot_hash`.
- Reuse: if rows for S with `provenance == forward_nightly` exist, reuse them (same H); otherwise compute with `force=True` for S only.
- Historical backfills must not write sessions that already have forward rows.

**C5 Readiness and recorder binding.**
- The driver computes S (unchanged rule) and H = `_readiness_snapshot_id` (unchanged), and evaluates readiness(S) on the forward run.
- It calls `run_paper_bots(as_of=<clock>, root, decision_session=S, snapshot_hash=H, challenger_engines=...)`.
- The recorder gates readiness on S and takes candidates only from rows with `snapshot_hash == H`.
- Its field mapping: `symbol` ← `yahoo_ticker`, `latest_price_date` ← `price_as_of_date`, plus `current_price` and `instrument_currency`.
- It requires `run_completed_at ≤ as_of` and an age ≤ 24 h.
- The live publication no longer feeds the recorder. The driver's publication-hash comparison (`daily_paper.py:283-284`) is replaced, not removed: the driver raises unless the recorder result's snapshot (`PaperBotRunResult` snapshot field) equals H. The guarantee "the gate PASS and the decisions bind to one run" stays.

**C6 Challengers.**
- B2-o: optimiser input = stamped rows with `is_adjusted` True, converted by `eur_basis_prices(..., known_by=cut)`. The engine's `known_at ≤ cut` filter is unchanged. If skfolio is missing: `NO_NEW_TRADE: weight engine sk_min_cvar is not available`.
- B1-r: `build_pit_panel` with scope `listing:sp500:all`, decision times = the stored t_S of each forward run that has a feature vintage (the panel then needs the census dated t_S's UTC day, which the capture-first order gives), features from C9, and EUR adjusted prices with C1 `known_at`. If the preflight fails: `NO_NEW_TRADE: ranker scores gbdt_rank_63 are not available`, and the preflight list goes into the run JSON. B1-r therefore ranks S&P 500 stocks only.

**C7 Session opens and fills.**
- Store `session_opens.parquet` (append-only), columns: `instrument_id`, `session_date`, `open`, `volume`, `currency`, `dividends`, `stock_splits`, `actions_evidenced`, `provider_symbol`, `source`, `provider`, `known_at` = retrieval time.
- Instruments: the union over bots of the targets of non-terminal decisions and the held positions (read only).
- The job takes the same mutex `Global\ETF-Cockpit-Data-Jobs` (`scripts/scheduled_refresh.ps1:44-47`).
- Config: `fill_time_utc: "15:00"`, with the comment "after every listing venue has opened and after the 14:45/13:45 UTC opening observation".
- Fill price (one source for `next_session_open` fills): the latest observation for (instrument, session) with `known_at ≤ fill_time`. If there is none: miss `price_not_known_at_fill_time` (same reason). `volume > 0`, the currency check and `require_actions` use the observation. The daily bar and `ledger_bar` are not used for these fills; they stay for valuation marks and corporate-action sync.
- A split on the fill session (observation `stock_splits` ≠ 0): miss `split_on_fill_session`; the retry rules apply.
- Delisting-day close fills are unchanged (daily bar close).

**C8 Driver and status.**
- `load_settings_bundle(root).controls.paper.enabled` false → skip the recorder and execution, then continue with refresh and publish (stage `paper_disabled` in the run JSON).
- A readiness FAIL also skips the recorder and execution, and the refresh still runs (tomorrow needs tonight's bars). The run exit code stays non-zero on a FAIL.
- `--dry-run` leaves `scheduled_refresh.ps1:39` and its header line 3.
- A `partial` run is accepted only if every cadence-due B0-B3 bot has an `available` record and every unavailable record is B1-r or B2-o with a `NO_NEW_TRADE` reason. The run JSON lists each bot outcome. Otherwise the run raises. This is a bounded relaxation of today's rule (`daily_paper.py:308-309` raises on any non-`available` status), taken from the activation plan of 2026-11-19, §5.3 step 6.

**C9 Feature vintages.**
- `data/derived/feature_vintages/<S>.parquet` is written once by the forward run, from the frame `FeatureService.compute_features(publish=False)` returned for S.
- Extra columns: `instrument_id`, `date` = S, `known_at` = `available_at` = t_S (`run_completed_at`), `pit_grade` = `observed`, `run_id`, `snapshot_hash`. Readers use t_S as the decision time (C6), never the session end.
- An existing file is never rewritten. A write failure is logged and does not block the run.

## 5. Failure modes

| Trigger | Behaviour | Reason text |
|---|---|---|
| Page fetch/parse/guard fails | No capture; bots run on last night's census | `capture failed: <cause>` (run JSON) |
| No census for S | readiness FAIL | `no visible census for listing:sp500:all on S` |
| Coverage < 0.95 | readiness FAIL | existing detail |
| Job starts after 00:00 UTC | Capture is dated D+1, S = D has no census: FAIL that night | as above |
| Last night's refresh failed | S falls back to an older session; its forward run is older than 24 h or admits no fresh rows: no decision | existing age / staleness reasons |
| Price row known after t_S | forward run raises | `price known after run time` |
| Forward run has no admitted rows | readiness `scored_run` FAIL | existing |
| `completed_at` < S end, or age > 24 h | run raises / recorder unavailable | existing age reason |
| Due B0-B3 bot unavailable | driver raises | `partial not accepted: <bot>` |
| skfolio missing / short history | B2-o or B1-r `NO_NEW_TRADE` | C6 texts |
| Opens job late, failed or absent | fill miss, then the existing retry/grace rules | `price_not_known_at_fill_time` |
| Split on fill session | fill miss | `split_on_fill_session` |
| Row without stamps | invisible to PriceBook/optimiser/panel | existing per-bar rules |
| Second same-day capture | skipped; first kept | `capture kept: first of day` |
| `ingest_sp500` run on forward root | census deleted: readiness FAIL | documented rule |
| `controls.paper.enabled` false | stop after readiness | `paper_disabled` |
| Currency conflict (P1) | instrument unavailable in EUR basis | existing FX reason |

## 6. Required tests (for the code PRs; about one per behaviour)

1. C1: new, revised and unchanged rows; a uniform `adjusted_close` re-base is not a revision; a dividend correction is a revision; both writers and rollback call the function; the migration fills `known_at` from `ingested_at` and leaves null rows null.
2. No look-ahead: no bar with `known_at` > cut reaches PriceBook, optimiser or panel.
3. C2: page fixture → ledger capture + census; second same-day run skipped; header and row-count guards fail closed.
4. Binding: verified USD non-US-ISIN unique → bound; two records → unbound `ambiguous_universe_records`.
5. C3: missing census → FAIL; present scope with 0 members → FAIL; licensed interval fixture behaves as before.
6. C4: `completed_at` stamped and checked; price row with `known_at` > t_S → raise; `provenance`; changing `current_price` changes `snapshot_hash`; reuse rule.
7. C5: readiness uses S; candidates only from H; recorded snapshot ≠ H → driver raises.
8. C8: `partial` rules; paper-disabled and readiness-FAIL skip the paper stages and still refresh.
9. C7: fill with observation known ≤ fill time; miss when later; split on fill session → miss.
10. C6/C9: B2-o weights from a stamped EUR fixture; B1-r `NO_NEW_TRADE` with the preflight list; B1-r fits and scores on a synthetic vintage fixture that passes the preflight; a vintage file is written once.

## 7. Accepted limitations

- Two-session data lag (data of S, decision on night S+1, fill on the next session after the decision date).
- B1-r records `NO_NEW_TRADE` for about 2 years after the first capture.
- Only S&P 500 stocks and observed-trading ETFs are bot-eligible; other stocks stay `survivorship_unverified`.
- Asian listings fill at their open with a 15:00 UTC clock after their close (the price is still known at the fill time).
- A provider change of `adjusted_close` that keeps every one-session return is not detected (no PIT effect on returns).
