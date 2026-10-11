# Tutorials

Release version: `1.1.0b1`.

Step-by-step tasks for the offline core workflow. Each step names a control as it
appears on screen (in bold) and the workspace that holds it; see
[Workspaces and navigation](WORKSPACES.md) for the page map and the
[user guide](USER_GUIDE.md) for how to read the evidence. The application is
local-first and `execution_allowed=false`: no tutorial connects a broker or sends
an order. Use your own files and synthetic examples; never put credentials in
notes, imports or exports.

## 1. Start the application and bootstrap data

1. Launch the packaged release with `Run_ETF_AI_Cockpit_EXE.bat`, or from a
   source checkout with `python scripts/run_app.py`. The app opens in your
   browser on `http://127.0.0.1:8550`. `python scripts/run_app.py --smoke`
   builds the service snapshot without opening the UI.
2. Open Home, then First-run Setup. Choose the output currency, asset scope,
   risk profile, target horizon and analysis depth.
3. In the Data source step choose the **Offline bootstrap**. `sample` creates a
   shipped, identity-only universe: it contains instruments but no fabricated
   prices. `bulk` checks a local CSV or Parquet file you name in **Local bulk
   price file**; it needs date, instrument identity and an `adjusted_close`
   (or `adj_close`) column. In this release the bulk check validates the file
   and reports the result but writes no price files, so prices are imported in
   step 6.
4. Enter **Initial tickers (comma separated)**. Offline or unresolved tickers
   stay disabled until validated; **Validate tickers online (opt-in)** is
   opt-in and never required.
5. Select **Save setup**. Setup stores preferences only; it never grants broker
   or provider write authority.
6. On Simple Scores open **Renew/import local files** and use **Import prices**
   (and, as needed, **Import FX rates**, **Import ETF factsheets**,
   **Import ETF holdings**, **Import manual notes**). Files are copied to raw
   storage and validated before they replace clean data. **Validate current
   data** performs a dry run and **Rollback prices** restores the previous clean
   price snapshot.
7. Open Data Health. Each store is classified as healthy, stale, missing,
   corrupt, schema-mismatched or unavailable. Missing data stays missing; do
   not proceed to scoring while the stores you need are unavailable.

`python scripts/update_data.py --sample` regenerates deterministic sample data
for fallback and testing only. Refreshing from Yahoo Finance
(**Refresh yfinance data** on Simple Scores) is an optional network provider,
subject to its own terms; its failure is visible and does not block local work.

## 2. Add and manage instruments

1. Open Universe. Use **Tier** and **Search universe** to inspect the Primary,
   Secondary and Sparebanken tiers.
2. Select **Add record** and fill the fields (ID, Name, ISIN, Yahoo ticker,
   Asset type, Tier, Currency, Region, Sector and so on). Select **Validate and
   add**. A rejected record shows the reason; leveraged and inverse products are
   flagged for manual review.
3. To load many rows select **Import**, paste CSV, TSV or JSON rows or a local
   path, then **Validate only**, **Preview import** and **Apply to pending changes**; for large inputs use
   **Resume next chunk**. **Cancel import** stops it.
4. Staged changes are not final until you select **Save validated changes**.
   **Edit**, **Identity** and **Classification** on each row show or change
   the record and its identity and classification evidence.
5. Provider and licence limits for each source are on Provider Status and Data
   Catalogue. Historical comparison needs point-in-time membership; current
   membership alone can introduce survivorship bias.

## 3. Research an instrument

1. Use the **Search or jump to** to jump to a page, for example Stock Research or
   Instrument Detail, or open an instrument from Simple Scores.
2. On Scores, read the three score groups and their component tables. Check the
   as-of date, coverage, freshness and warnings first.
3. On Instrument Detail check the instrument identity, holdings coverage and
   dates, events, and the limitations listed with each section. For stocks open
   Stock Research and read each metric with its reporting period and source.
4. On Comparison compare two instruments on aligned dates; unavailable values
   stay blank and are not treated as equal. **Export CSV** and **Save workspace**
   keep the result.
5. **Evidence mode** in the header selects the evidence detail preference
   (Compact, Default or Advanced). Record your own conclusion on Decision Journal (**Save note**) so it is stored beside the
   evidence snapshot.

## 4. Review forecasts and training evidence

1. On Simple Scores the Workflow section runs the steps in order:
   **1. Refresh yfinance data** (optional network provider), **2. Run
   algorithms**, **3. Run forecasting models** and **4. Show scores**. The
   deterministic baseline is always the core path; TimesFM and Toto are optional
   and show as unavailable when their packages or weights are absent.
2. On Forecast Lab read forecast dates, horizons, matured outcomes and the model
   cards. Unmatured outcomes are not scored.
3. Training Centre records experiments, runs, metrics and the model registry.
   **Refresh** reloads the run list. **Generate seeded scenario** produces a
   synthetic fixture marked as not eligible for promotion. **Refresh validation
   report** and **Retain trial evidence** keep the walk-forward validation
   evidence. Only a completed run with verified artefacts and explicit human
   approval can become a challenger; approval is research status only and cannot
   enable any live action. This release records and compares experiments; it does
   not claim a full automated training pipeline.

## 5. Explore a portfolio and use the paper account

1. Import portfolio history on Import & Export (import type `portfolio_history`;
   preview, then **Commit validated import**). On Portfolio Sandbox review the
   holdings, then use **Run what-if** and **Validate rebalance preview**. Results are scenarios; nothing is submitted.
   **Prepare draft proposal** prepares a draft for review.
2. Open Operations Centre. Select **Open local paper account** with a **Paper
   account ID** and **Opening cash (EUR)**. The Environment selector offers
   `Paper proposal` and `Live (disabled)`; live is unavailable.
3. Select **Validate proposal review**. A proposal needs validated optimiser
   output and all policy gates; otherwise review fails with a reason. Enter the
   **Validated proposal ID** and choose **Accept to paper**, **Reject proposal**
   or **Defer proposal** (with its reason). **Auto-paper (local)** is a local
   simulation helper, not a broker connection.
4. Record what happened with **Record fill** (**Paper order ID**, **Fill
   quantity**, **Fill price**), **Record adjusted-close mark**, **Apply corporate
   action** and **Mature outcome**. Replace the default values with real
   observations; the checksum fields expect the SHA-256 of your source file.
   **Cancel paper order** cancels an open paper order.
5. The ledger is append-only and replays after restart. Simulated fills and fees
   are not brokerage outcomes. Use Forward Evidence Diary to log observations
   and update outcomes only after their horizons mature.

## 6. Back up and restore

1. Settings holds encrypted backups. Enter a **Recovery key** of at least 16
   characters (it is never logged or stored), then **Create encrypted backup**.
   The archive is written to `exports/storage/cockpit-encrypted.backup`.
   **Validate latest backup** checks it, and **Run recovery drill** restores a
   fresh archive into a separate directory to prove it works.
2. Import & Export holds a plain archive: set **Backup archive destination** and
   select **Create backup**. To restore, enter the **Restore archive** path and
   select **Validate restore preview**. Nothing is written until you select
   **Commit restore**; **Cancel restore** leaves the destination unchanged.
3. Keep the recovery key separately; a lost key cannot be recovered. Before
   updating the application, back up first and check the restore preview.
4. In Import & Export choose Scoreboard, Audit packet, Decision journal or
   Watchlist, disclose **Export destination path**, then select **Export**.
   Exports go to an explicit local path; restricted
   source text can be omitted while permitted provenance remains.

## 7. Handle an incident

1. A failed action shows a message in the activity strip; the page Errors &
   Recovery and Jobs & Activity keep recent failures and job state.
2. Keep the original files and logs. Record the visible message and the affected
   data date.
3. For an unknown or contradictory paper state, stop paper actions, record it with
   **Record incident** on Operations Centre and follow the
   [incident runbooks](../operations/INCIDENT_RUNBOOKS.md). Do not retry an
   uncertain action or edit ledger files.
4. For application, data and job failures follow the
   [operator runbook](../operations/OPERATOR_RUNBOOK.md).
