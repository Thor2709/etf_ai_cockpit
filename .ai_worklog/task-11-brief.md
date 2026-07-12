### Task 11: Universe Store, Watchlists, Onboarding and Asset Guardrails

**Issues:** `ISSUE-0068`, `ISSUE-0018`, `ISSUE-0017`, `ISSUE-0056`.

**Files:**
- Create: `src/etf_cockpit/data/universe_store.py`
- Create: `src/etf_cockpit/app/pages/universe_manager.py`, `onboarding.py`
- Create: `tests/test_universe_store.py`, `tests/test_onboarding.py`, `tests/test_asset_guardrails.py`
- Modify: `src/etf_cockpit/core/config.py`, `configs/universe.yaml`, `src/etf_cockpit/app/router.py`, `src/etf_cockpit/app/pages/settings.py`

**Interfaces:**
- `UniverseRecord` fields: ID, name, ISIN/status, Yahoo ticker, asset type, tier, group, enabled, data policy, currency, region, sector, theme and notes.
- `validate_universe(records) -> UniverseValidationReport`.
- `save_universe(records, expected_revision: str) -> UniverseSaveResult` uses backup, atomic write and revision conflict protection.
- `support_decision(asset_type, frequency, leveraged, inverse) -> SupportDecision`.

- [ ] **Step 1: Write CRUD, duplicate and guardrail tests**

Cover add/edit/disable/remove; duplicate ID/ISIN/ticker across tiers; explicit `needs_verification`; no workflow auto-run after save; daily ETF/stock support; intraday/futures/options/crypto unsupported; leveraged/inverse high-risk.

- [ ] **Step 2: Implement migrated universe persistence**

Import current primary YAML and candidate CSV into one versioned store while retaining export back to existing formats for compatibility. Preserve all 15 Sparebanken rows and unknown ISIN states.

- [ ] **Step 3: Build Universe/Watchlist UI**

Use Primary, Secondary and Sparebanken tabs, search/filter, validated edit dialog and status column. Save only after validation; show pending-refresh without triggering refresh.

- [ ] **Step 4: Build first-run wizard**

Collect base currency, region, asset scope, risk profile, horizon and initial tickers; validate locally/yfinance when online; explain local-only evidence and non-advice; support offline completion with unresolved tickers disabled.

- [ ] **Step 5: Test clean first run and package**

Run with temporary empty root, complete wizard using computer use, restart, verify persisted universe, then run source/full tests and Wave 5 package/browser gate.

---

