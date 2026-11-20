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
| `score_history_backfill*.parquet` (backfill store) | forward score run and historical backfill (`backfill_score_history`) | readiness and recorder (both provenances, C4); historical replay (`historical_backfill` only) |
| `data/derived/feature_vintages/<session>.parquet` (new) | forward score run | B1-r panel |
| `data/validated/prices/session_opens.parquet` (new) | session-opens job | execution fills, B0 shadow |
| decision records, paper ledgers | recorder, execution (unchanged) | reports, opens job (read only) |

Rule: `scripts/ingest_sp500.py` must not run on the forward root. Its scope replacement would delete the census rows,
and readiness then fails closed.

## 3. Timing (UTC; winter shown; local = CET)

```text
Night D (job 21:30 UTC = 22:30 CET); all paper stages hold the cross-process writer guard
 21:30  a. S&P capture: fetch page -> bind -> ledger capture (snapshot_date=D, known_at~21:31)
           -> census rows [D, D+1)          (failure: logged; tomorrow's readiness fails)
 ~21:32 b. S = latest VWCE session < D and <= report_date, where report_date = data_report.as_of_date
           of a HeadlessSession.refresh_snapshot() build on the stored data (no provider call),
           made before step g. The stored data are the prices committed by night D-1's refresh.
           No new session (S <= as_of_date of the latest stored forward run): skip b-f with
           reason no_new_session (not an error), continue with g.
           t_S = clock. Forward score run(S) (guard: every consumed known_at <= t_S),
           membership/FX known by S 23:59:59 (census of night D-1)
           run_completed_at = t_S; feature vintage <S>.parquet (known_at = t_S)
        c. readiness(S) on run H (8 checks)            -> FAIL: skip d-f
        d. paper enabled? no -> skip e-f (like --dry-run)
        e. recorder(as_of = clock, decision_session = S, snapshot = H; slot month = month of S)
           -> decision decided_at = t_d (date d = UTC date of t_d); driver checks candidate_snapshot == H
        f. execution: fill intents for sessions F with d < F < as_of.date(); AI account
 ~21:45 g. refresh prices + FX (2.5-3.5 h)  -> stamps (C1); bars of D for tomorrow's S = D
           g runs whatever b-f do (finally-style); a failure in b-f keeps the exit code non-zero
        h. live rescore + publish (UI only)
Day F (first VWCE session after d)
 13:30/14:30 US open; 07:00/08:00 Xetra open
 14:45 UTC (13:45 UTC in CEST)  session-opens job: observe open of target + held instruments
                     -> session_opens rows (session_date = bar date = F, known_at = retrieval time)
 15:20  fill_time_utc: fill price = observed open with known_at <= 15:20 (Xetra closes 15:30 UTC in CEST)
Night F+1 (as_of.date() = F+1 > F): step f books the fill at F 15:20 with that price.
```

Lag summary: data of session S → decision on night S+1 → fill at the open of the first session after the
decision date → booked on night F+1. The first night after go-live fails readiness (no prior census).

The daily job runs every day. A Monday night has S = Friday, because Monday's bars arrive only with
Monday night's refresh (step g). Saturday night already used S = Friday, so Sunday and Monday nights skip
with `no_new_session`.

Example: the month change on Sunday 1 November 2026.

| Night D | S | Paper stages | Slot month |
|---|---|---|---|
| Fri 30 Oct | Thu 29 Oct | run | 2026-10 |
| Sat 31 Oct | Fri 30 Oct | run (new session) | 2026-10 |
| Sun 1 Nov | Fri 30 Oct | skip `no_new_session` | none |
| Mon 2 Nov | Fri 30 Oct | skip `no_new_session` | none |
| Tue 3 Nov | Mon 2 Nov | run; first November decision, d = 3 Nov | 2026-11 |

The decision of Tue 3 Nov fills on F = Wed 4 Nov: the opens job observes at 14:45 UTC (US DST ended on
1 Nov, so the US opens at 14:30 UTC), the fill time is 15:20 UTC, and night Thu 5 Nov books the fill. With the
month of the clock as slot month, a run on 1 Nov would put October data (S = 30 Oct) into the November slot;
the month-of-S rule prevents this.

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
- The skip key is census presence. If census rows exist for (`listing:sp500:all`, today's UTC date), skip. If the ledger already has a capture for that day but its census is absent, do not capture again: parse and bind the stored raw payload of that capture (`load_raw_payload`) and write the census, with `identity_known_at` = rebuild time (`member_known_at` stays the capture `known_at`). This allows at most one capture per scope per day.
- `record_listing_capture(rows=[{"instrument_id": id} for bound], source="wikipedia:sp500_constituents", scope="listing:sp500:all", known_at=<retrieval time>, raw_payload=<page bytes>, snapshot_date=<UTC date of known_at>)`.
- Binding (item 6, O2 accepted): page row → exactly one universe-store record with `asset_type` stock, `isin_status` verified, configured `currency` USD, ticker = `sec_ticker(page ticker)` (Yahoo ticker without exchange suffix). Otherwise the row is unbound with a reason: `ambiguous_universe_records`, `no_verified_usd_stock`. The old US-ISIN filter gives 93.2% coverage, and readiness then fails (P2).

**C3 Index-coverage census.**
- Writer: after a recorded capture, append one row per page member: `scope`, `source_ticker`, `instrument_id` (null if unbound), `valid_from` = snapshot date, `valid_to` = snapshot date + 1 day, `member_known_at` = capture `known_at`, `identity_known_at` = capture `known_at` (null if unbound), `binding_status` `bound`/`unbound`, `reason`.
- The write is an atomic replace of the whole file with old rows + new rows. Rows are never deleted. If rows exist for (scope, `valid_from`), the writer skips.
- Reader changes in `_index_coverage_check`, only for a scope where the ledger has a `source_kind='self'` capture (forward use). A scope with licensed captures only behaves as before.
  1. Such a scope with no active row for the day → FAIL `unavailable: no visible census for <scope> on <day>`.
  2. Members = 0 for such a scope → FAIL.
- Unchanged: threshold 0.95, duplicate-row FAIL, unbound counted against coverage.

**C4 Forward score run.**
- `backfill_score_history(root, start=S, end=S, every=1, force=<reuse rule>, completed_at=t_S)` passes `completed_at` to `score_as_of`.
- When `completed_at` is given: `created_at` = `completed_at`, and it must be ≥ S 23:59:59 UTC, else raise. `provenance` = `forward_nightly`.
- Loader: `load_backfill_score_history` (`data/score_history_backfill.py:28-36`) keeps only `historical_backfill` rows today. It gets a provenance set. Readiness (`portfolio/paper_bots_readiness.py:160`), the recorder (C5) and the merge step of the backfill writer (`application/score_backfill.py:249-250`, history and eligibility, so a later write keeps the forward rows) read {`historical_backfill`, `forward_nightly`}. The historical replay readers keep the default {`historical_backfill`} and exclude forward rows: `portfolio/paper_bots_replay.py:75`, `scripts/replay_paper_bots_from_backfill.py:66`, `scripts/export_replay_ledger.py:77`. Per session the store holds rows of one provenance only.
- Price guard (forward mode only). A consumed row is a price row that enters the run input `known` (`score_backfill.py:437-440`): date ≤ S, not excluded, and instrument enabled after the membership snapshot. If a consumed row has `known_at` > t_S, the run raises. If a consumed row has a null `known_at`, its instrument is not admitted, with reason `price_unstamped` in the eligibility log; there is no zero-fill and no raise. The driver reads t_S while it holds the cross-process writer guard, so no write can come between the clock read and the score run.
- The membership, FX and feature `known_by` stay S 23:59:59.
- New run fields: `current_price`, `instrument_currency` (via `_BASE_HISTORY_EXTRA`); both are in `snapshot_hash`.
- Reuse: if rows for S with `provenance == forward_nightly` exist, reuse them (same H); otherwise compute with `force=True` for S only.
- Eligibility rows get a `provenance` column; `load_backfill_eligibility` filters it with the same provenance set as `load_backfill_score_history`, so forward eligibility rows (for example `price_unstamped`) stay out of historical replay. A legacy row without the column counts as `historical_backfill`.
- The manifest writes a `provenances` list taken from the stored rows, not the hardcoded `historical_backfill` (`score_backfill.py:292`). The list replaces the singular `provenance` key (no reader in `src/` or `tests/`).
- Historical backfills must not write sessions that already have forward rows: they skip such sessions before the fingerprint check and keep the forward rows unchanged.

**C5 Readiness and recorder binding.**
- The driver computes S (rule in §3 step b) and H = `_readiness_snapshot_id` (unchanged), and evaluates readiness(S) on the forward run.
- It calls `run_paper_bots(as_of=<clock>, root, decision_session=S, snapshot_hash=H, challenger_engines=...)`.
- The recorder reads the same store and run as readiness: `load_backfill_score_history` with both provenances, rows for S with `snapshot_hash == H`. It no longer reads `_load_published_score_history` (`paper_bots.py:171`) or the publication bindings. It gates readiness on S, not on `cutoff.date()` (`paper_bots.py:133`).
- Month rule: the monthly slot month is the month of S. This replaces `cutoff.strftime("%Y-%m")` and the current-month filter on publication `known_at` (`paper_bots.py:192-202`).
- Its field mapping: `symbol` ← `yahoo_ticker`, `latest_price_date` ← `price_as_of_date`, plus `current_price` and `instrument_currency`.
- It requires `run_completed_at ≤ as_of` and an age ≤ 24 h (`paper_bots.py:894-898`, measured from `run_completed_at`).
- Replaced check (immutable record): today the scoreboard bytes hash and the publication binding record tie the candidates to an immutable record. After the change, the stored forward run rows for S are that record: the recorder recomputes `_content_hash` over them (`score_backfill.py:799-803`) and requires it to equal H. H is set at `score_backfill.py:541`, before `config_fingerprint` is added (`:347`), and `_content_hash` drops only `snapshot_hash`; so the recorder drops `snapshot_hash` and `config_fingerprint` before it recomputes. `provenance` = `forward_nightly` and `created_at` = `completed_at` are set inside `_history_run`, before `:541`, so H covers them. This keeps every stored H unchanged (smaller change than moving H after `:347`). Forward rows are never rewritten (reuse rule; historical backfills skip forward sessions).
- Replaced check (driver): the publication-hash comparison (`daily_paper.py:283-284`) is replaced, not removed. `PaperBotRunResult` gets a field `candidate_snapshot` = the snapshot of the run the recorder loaded and verified tonight. It is set whether or not a slot gets a new record (an already filled slot does not change it); it is None only when the recorder could not load and verify that run. The driver raises unless `candidate_snapshot == H`. The existing `snapshot_hash` field is the snapshot set of all records of the month, earlier records included (`paper_bots.py:343-345,429,438`), so it is not compared. The guarantee "the gate PASS and the decisions bind to one run" stays.

**C6 Challengers.**
- B2-o: optimiser input = stamped rows with `is_adjusted` True, converted by `eur_basis_prices(..., known_by=cut)`. The engine's `known_at ≤ cut` filter is unchanged. If skfolio is missing: `NO_NEW_TRADE: weight engine sk_min_cvar is not available`.
- B1-r: `build_pit_panel` with scope `listing:sp500:all`, decision times = the stored t_S of each forward run that has a feature vintage (the panel then needs the census dated t_S's UTC day, which the capture-first order gives), features from C9, and EUR adjusted prices with C1 `known_at`. If the preflight fails: `NO_NEW_TRADE: ranker scores gbdt_rank_63 are not available`, and the preflight list goes into the run JSON. B1-r therefore ranks S&P 500 stocks only.

**C7 Session opens and fills.**
- Store `session_opens.parquet` (append-only), columns: `instrument_id`, `session_date`, `open`, `volume`, `currency`, `dividends`, `stock_splits`, `actions_evidenced`, `provider_symbol`, `source`, `provider`, `known_at` = retrieval time.
- The job sets `session_date` from the bar date and drops a bar whose date is not F. `actions_evidenced` = false when the provider returns no action columns for that row.
- Instruments: the union over bots of the targets of non-terminal decisions and the held positions (read only).
- The job does not wait on the data-jobs mutex `Global\ETF-Cockpit-Data-Jobs` (`scripts/scheduled_refresh.ps1:44-47`); it writes only its own store, with an atomic replace of the whole file (old rows + new rows). Bounded start check: the job observes only when today is a VWCE session and the clock is before `fill_time_utc`; otherwise it logs the reason and writes nothing.
- Config: `fill_time_utc: "15:20"`, with the comment "after every listing venue has opened, after the 14:45/13:45 UTC opening observation, and before the 15:30 UTC Xetra close in CEST".
- Fill price (one source for `next_session_open` fills): the latest observation for (instrument, session) with `known_at ≤ fill_time`. If there is none: miss `price_not_known_at_fill_time` (same reason). `volume > 0`, the currency check and `require_actions` use the observation. The daily bar and `ledger_bar` are not used for these fills; they stay for valuation marks and corporate-action sync.
- A fill miss is terminal: there is no retry on a later session. Only a `deferred` record (waiting for settled cash) is retried (`paper_bots_execution.py:1197-1200`).
- One canonical open per session: the observation (the fill price in `_attempt`, `paper_bots_execution.py:1401-1417`). Four more call sites change:
  1. Legacy fill-basis check in the corporate-action sync (`paper_bots_execution.py:741-744`): applies only to fills not taken from an observation. The `fill_recorded` ledger event (read at `paper_bots_execution.py:735-737`) names its price source.
  2. Split check on the fill session (`split_ratio_between`, `paper_bots_execution.py:1425`, raises today): a split on the fill session (observation `stock_splits` ≠ 0, or a split not known at the fill time) becomes the per-order miss `split_on_fill_session` inside the order handling, not a stage raise. The miss is terminal.
  3. B0 VWCE shadow (`portfolio/paper_trading.py:1737-1752`): uses the same observed VWCE open, not the daily series `open`; the flow stores it as `executed_open` (`:1832`) and names the observation as its price source.
  4. B0 shadow valuation re-check (`portfolio/paper_trading.py:1889-1897`): today it compares the stored `executed_open` with the daily `open` and raises `historical_price_revised`. For an observation-sourced flow it compares `executed_open` with the stored observation instead; the close and prefix-hash checks stay.
- The C7 build write set includes `portfolio/paper_trading.py`.
- Delisting-day close fills are unchanged (daily bar close).

**C8 Driver and status.**
- `load_settings_bundle(root).controls.paper.enabled` false → skip the recorder and execution, then continue with refresh and publish (stage `paper_disabled` in the run JSON).
- A readiness FAIL also skips the recorder and execution, and the refresh still runs (tomorrow needs tonight's bars). The run exit code stays non-zero on a FAIL.
- No new session (§3 step b) → skip the paper stages with stage `no_new_session` in the run JSON. This is not an error (exit code 0 when the refresh succeeds).
- The refresh runs whatever the paper stages do (finally-style). Today the `_StageFailure` handler (`daily_paper.py:345-346`) returns the run as blocked; with the new order it would return before the refresh. A paper-stage failure keeps a non-zero exit code.
- `--dry-run` leaves `scheduled_refresh.ps1:39` and its header line 3.
- A `partial` run is accepted only if every cadence-due B0-B3 bot has an `available` record and every unavailable record is B1-r or B2-o with a `NO_NEW_TRADE` reason. The run JSON lists each bot outcome. Otherwise the run raises. This is a bounded relaxation of today's rule (`daily_paper.py:308-309` raises on any non-`available` status), taken from the activation plan of 2026-11-19, §5.3 step 6.
- Paper decisions come only from this nightly driver. The UI/MCP `paper_bots_run` workflow records nothing and returns `unavailable` ("forward decisions run only in the nightly job"), so there is one decision path.

**C9 Feature vintages.**
- `data/derived/feature_vintages/<S>.parquet` is written once by the forward run, from the frame `FeatureService.compute_features(publish=False)` returned for S.
- Extra columns: `instrument_id`, `date` = S, `known_at` = `available_at` = t_S (`run_completed_at`), `pit_grade` = `observed`, `run_id`, `snapshot_hash`. Readers use t_S as the decision time (C6), never the session end.
- An existing file is never rewritten. A write failure is logged and does not block the run.

## 5. Failure modes

| Trigger | Behaviour | Reason text |
|---|---|---|
| Page fetch/parse/guard fails | No capture; bots run on last night's census; B1-r has no census for day D (t_S's UTC day) and records `NO_NEW_TRADE` | `capture failed: <cause>` (run JSON); C6 B1-r text |
| No census for S (scope with a self capture) | readiness FAIL | `no visible census for listing:sp500:all on S` |
| Coverage < 0.95 | readiness FAIL | existing detail |
| Job starts after 00:00 UTC | Capture is dated D+1, S = D has no census: FAIL that night | as above |
| Last night's refresh failed | S falls back to an older session: no new session, or its forward run is older than 24 h or admits no fresh rows: no decision | `no_new_session` / existing age / staleness reasons |
| No new session since the last forward run (weekend, holiday) | paper stages skipped; refresh runs; not an error | `no_new_session` |
| A paper stage raises | refresh and publish still run; exit code non-zero | stage error |
| Consumed price row known after t_S | forward run raises | `price known after run time` |
| Consumed price row with null `known_at` | instrument not admitted in the forward run | `price_unstamped` |
| Forward run has no admitted rows | readiness `scored_run` FAIL | existing |
| `completed_at` < S end, or age > 24 h | run raises / recorder unavailable | existing age reason |
| Recomputed content hash of the stored rows ≠ H | recorder unavailable; `candidate_snapshot` None; driver raises | content hash differs from H |
| `candidate_snapshot` ≠ H | driver raises | recorded snapshot differs from H |
| Due B0-B3 bot unavailable | driver raises | `partial not accepted: <bot>` |
| skfolio missing / short history | B2-o or B1-r `NO_NEW_TRADE` | C6 texts |
| Opens job late, failed or absent | terminal fill miss (no retry) | `price_not_known_at_fill_time` |
| No VWCE observation for a B0 shadow flow | terminal shadow miss: the flow is recorded with no trade, its cash stays uninvested, later flows continue | `missed_reason` = `price_not_known_at_fill_time` |
| Split on fill session | terminal per-order fill miss | `split_on_fill_session` |
| Row without stamps | invisible to PriceBook/optimiser/panel | existing per-bar rules |
| Census present for the day | capture skipped; first kept | `capture kept: first of day` |
| Ledger capture present, census absent | census rebuilt from the stored raw payload (`identity_known_at` = rebuild time) | `census rebuilt from stored capture` |
| `ingest_sp500` run on forward root | census deleted: readiness FAIL | documented rule |
| `controls.paper.enabled` false | stop after readiness | `paper_disabled` |
| Currency conflict (P1) | instrument unavailable in EUR basis | existing FX reason |

## 6. Required tests (for the code PRs; about one per behaviour)

1. C1: new, revised and unchanged rows; a uniform `adjusted_close` re-base is not a revision; a dividend correction is a revision; both writers and rollback call the function; the migration fills `known_at` from `ingested_at` and leaves null rows null.
2. No look-ahead: no bar with `known_at` > cut reaches PriceBook, optimiser or panel.
3. C2: page fixture → ledger capture + census; second same-day run skipped; capture without census → census rebuilt from the raw payload; header and row-count guards fail closed.
4. Binding: verified USD non-US-ISIN unique → bound; two records → unbound `ambiguous_universe_records`.
5. C3: missing census → FAIL; present scope with 0 members → FAIL; licensed interval fixture (no self capture) behaves as before.
6. C4: `completed_at` stamped and checked; price row with `known_at` > t_S → raise; null `known_at` → instrument not admitted; `provenance`; replay readers exclude forward rows (history and eligibility; a legacy eligibility row without `provenance` counts as historical) and a historical write keeps them; a stored forward run round-tripped through parquet gives the same H with `snapshot_hash` and `config_fingerprint` dropped; changing `current_price` changes `snapshot_hash`; reuse rule.
7. C5: readiness uses S; candidates only from the backfill store rows with H and a matching content hash; slot month = month of S; `candidate_snapshot` ≠ H → driver raises.
8. C8: `partial` rules; paper-disabled, readiness-FAIL, `no_new_session` and a paper-stage failure skip the paper stages and still refresh.
9. C7: fill with observation known ≤ fill time; miss when later, with no retry; observation with a bar date ≠ F dropped; split on fill session → per-order miss; B0 shadow uses the observed open and a later shadow valuation does not raise `historical_price_revised` for it; legacy fill-basis check skips observation fills.
10. C6/C9: B2-o weights from a stamped EUR fixture; B1-r `NO_NEW_TRADE` with the preflight list; B1-r fits and scores on a synthetic vintage fixture that passes the preflight; a vintage file is written once.

## 7. Accepted limitations

- Two-session data lag (data of S, decision on night S+1, fill on the next session after the decision date).
- B1-r records `NO_NEW_TRADE` for about 2 years after the first capture.
- Only S&P 500 stocks and observed-trading ETFs are bot-eligible; other stocks stay `survivorship_unverified`.
- Asian listings fill at their open with a 15:20 UTC clock after their close (the price is still known at the fill time).
- A provider change of `adjusted_close` that keeps every one-session return is not detected (no PIT effect on returns).
- A late, failed or absent opens job loses that fill (terminal miss).
