# Point-in-time evidence and explicit source conflicts

**Status:** accepted

**Date:** 2026-07-27

## Context

Research and replay are invalid if later revisions, publication knowledge or
conflicting sources leak into an earlier decision.

## Decision

Identity is stable across listings and revisions. Evidence retains valid,
publication/acceptance, retrieval and knowledge chronology, provenance and
revision identity. Conflicts and missing chronology remain explicit and fail
closed; they are never silently merged or zero-filled.

ISSUE-0182 builds the research panel from explicit local observations or the
captured membership ledger at each decision time. Feature groups retain their
availability times. Adjusted EUR forward labels use the Xetra session calendar
for VWCE and use only outcome evidence known by the next session open. A
missing benchmark bar leaves the excess label unavailable. Validation keeps each
decision date together and excludes training
labels unavailable at the first validation decision.

### Per-bar price stamps (amendment 2026-11-20)

Every daily price bar carries `ingested_at`, `known_at`, `available_at` and
`actions_evidenced` (contract C1 of the
[forward paper path](../forward-paper-path.md), [ADR-0009](ADR-0009-forward-paper-path.md)).
One function, `stamp_price_availability` in `data/import_pipeline.py`, sets
them for both writers (`commit_price_import`, `universe_fetch.promote_staging`)
and for `rollback_latest_price_import`. A new or revised bar gets the
retrieval time, never an earlier time; a new bar is available at
min(session 23:59:59 UTC, retrieval time). An unchanged bar keeps its stamps; a
uniform `adjusted_close` re-base is not a revision. A legacy bar with
`ingested_at` and no `known_at` gets `known_at := ingested_at`; a bar without
stamps stays unstamped and is unavailable to every stamped reader.

### Reconstructed replay availability (amendment 2026-11-22, owner decision OD-1 = b)

A refetch that sees a small revision restamps the bar at the fetch time, so the
stored stamps alone shrink the strict past (97 of 142 tradable ETFs on
2024-06-28). Historical replay therefore reads prices through one rule,
`reconstructed_price_availability` in `data/import_pipeline.py`:

- every fetched bar counts as known and available at its session close
  (23:59:59 UTC), with its values as fetched (adjusted); an earlier stored
  stamp (a live fetch before the close) stays;
- a genuine bar with an empty stamp, or a stamp without a timezone, also counts
  at its session close (fork A, 2026-11-22: 21,157 of 4,615,340 genuine bars);
- 23:59:59 UTC is the project's session-close convention: the same as the
  ingest stamp (`stamp_price_availability`) and the replay decision time
  (`score_backfill`, `rank_validation`), so a bar is never visible before the
  decision time of its own session;
- every row it returns carries `pit_basis = "reconstructed"`, and results built
  from it keep that label;
- it applies at read time only. Stored `known_at` and `available_at` stamps are
  never rewritten; live readers keep them.

Replay readers: ETF admission (`ListingHistory.with_observed_trading`), rank
validation, the backtest and the paper-bot replay book
(`PriceBook.from_root(reconstructed=True)`; the run result carries `pit_basis`). Other sources under the same decision: Yahoo FX
counts at its close (`stamp_fx_availability`); ECB euro reference rates
(`data/ecb_fx.py`, source `ecb`, basis `ecb_publication`) count at their publish
time, 16:00 Frankfurt time (CET or CEST) on the rate day, or at the fetch time
if that is earlier; S&P 500 membership changes at their effective date
(`replay_membership.reconstructed_licensed_rows`: an incomplete licensed interval at
`valid_from`, its end at `valid_to`, both 00:00 UTC, `pit_basis` "reconstructed"; readers
`ListingHistory.from_root(reconstructed=True)` and `membership_frame(reconstructed=True)`); SEC
data at its filed date. The FX store keeps one rate per quote day and currency
against EUR (`prefer_ecb_rates`, applied by every FX writer): the ECB rate where
the ECB publishes one, else the Yahoo rate (for example CLP, COP, and TWD after
2020). A reader takes a row only from its own `available_at`, so before the
Yahoo close only the ECB rate of that day is visible. The macro path
`ecb_provider` keeps its `inferred` rows; it does not feed the FX store.
Reconstructed rows count as historical evidence for proof and tuning. Their
values can include later revisions: a later dividend or split rescales earlier
adjusted values (returns are unchanged), and a vendor correction shows at its
original session. The label keeps this visible, and promotion of a change still
needs forward confirmation.

## Consequences

As-of queries and replay require versioned evidence. ISSUE-0153 must resolve
the outstanding chronology/hash contract before dependent work treats it as
complete.

## Alternatives

Latest-value overwrites and provider-priority without conflict evidence were
rejected because they create look-ahead and irreproducible results.

## Evidence and links

[Bitemporal model](../bitemporal-vintage-model.md),
`src/etf_cockpit/data/bitemporal.py`, `tests/test_no_lookahead.py`.
