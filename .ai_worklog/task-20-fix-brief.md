# Task 20 fix pass - independent review findings

Base implementation: `22a95e8` on `wave5/task20-import-export`.

Fix every Critical/Important finding from the independent review before
integration. Do not broaden product scope or change authority; preserve
`execution_allowed=false`, existing atomic I/O and current Flet vocabulary.

## Required fixes

1. Canonical import routing and normalisation:
   - broker import must use the existing canonical holdings import/validation
     path and preserve its expected `current_holdings.csv` schema/path;
   - candidate import must preserve the runtime candidate CSV path/schema;
   - manual notes/news and ETF holdings must route through their existing
     normalisers/contracts so authority/provenance fields are retained;
   - do not silently write incompatible parquet aliases that runtime loaders
     ignore.
2. Preview integrity:
   - `ImportPreview` must be effectively immutable for commit purposes;
   - commit must recompute/verify the stored checksum and reject stale or
     mutated previews before any write;
   - keep previous clean output intact on rejection/write failure.
3. Input safety:
   - reject missing/NaN/blank manual-note text and news headlines;
   - RSS/XML list imports must require valid feed URLs or valid parsed item URL/
     headline/date data; reject malformed URL values and empty feeds.
4. Backup/restore:
   - scan file contents for credential/secret key material, not only filenames;
   - record excluded entries in the manifest while never exporting secrets;
   - validate supported payload schemas for known config/data files and reject
     unsupported schema versions before writes;
   - retain traversal, duplicate, checksum and stale-preview checks and atomic
     failure containment.
5. Visible operations:
   - expose truthful export actions for the approved scoreboard, audit packet,
     watchlist, paper-trade journal, decision journal and plan/issues snapshot;
   - separate restore validation preview from explicit commit/cancel state;
   - show destination paths and controlled success/error/unavailable states.
6. Charts/tables:
   - provide real observable history/equity/drawdown data descriptors, not only
     row-count text;
   - expose functional search/sort metadata/callback behaviour in the table
     helper without relying on colour alone.

## RED-GREEN-REFACTOR and verification

Add adversarial tests first for each fix, run them and record genuine failures;
implement the smallest compatible changes; rerun Task 20 and affected tests,
Ruff, compileall and diff checks. Update `.ai_worklog/task-20-report.md` with
fix evidence and commit the fix. Do not change issue closure state here; parent
will review and integrate.

## Final reviewer blockers to resolve

- Commit the validated broker preview frame rather than rereading a mutable
  source path after preview.
- Preserve existing ETF holdings when importing another instrument by using the
  canonical merge path.
- Make RSS URL-list imports either commit a supported feed-list representation
  or reject them during preview; never report valid then fail at commit.
- Reject non-numeric unsupported schema-version values in known restore payloads.
- Use the live decision-journal path and a canonical watchlist source for
  exports, and connect chart/table helpers to visible analytical surfaces with
  observable data and search/sort behaviour.
