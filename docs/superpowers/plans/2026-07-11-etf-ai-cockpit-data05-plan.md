# DATA-05 Verified Seed Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` with a fresh implementer and a fresh reviewer for each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install all 39 authorised seed exposures through the canonical revision-protected universe/registry path, with current official identity and provider evidence, exactly 25 independently deep-linkable EU technology subareas and a fixed 8-large/9-mid/8-small coverage split.

**Architecture:** The canonical registry from the preceding plan is preferred. If its migration is not yet authoritative, extend `UniverseRecord` through a schema-versioned compatibility record written solely via expected-revision save APIs. A seed is not installed as verified until its expected/observed source evidence checksum record passes.

**Tech Stack:** Python 3.13, Pydantic, PyArrow/DuckDB, requests/yfinance bounded probe, ISO MIC source cache, existing atomic universe store, Flet, pytest, Playwright/Chrome.

## Global Constraints

- No scope drift: DATA-05 owns monitored coverage only, not scoring, portfolio policy, research threshold or execution changes.
- Evidence, analysis, research state, portfolio review and user decisions stay separate; `execution_allowed` remains `false`.
- Preserve the revision-protected universe store, atomic I/O/recovery, Data Health, provider/evidence contracts, source-aware score eligibility, session trace, audit manifests, router and Flet shell.
- Use narrow adapters and migrations; do not perform unrelated refactoring.
- Do not initialise Git, create a worktree, commit, push, create a pull request, delete user data or modify a remote service.
- Every seed identifier receives live implementation-time official/exchange/provider verification; a table seed is not proof.
- A failed or conflicting seed is explicit staged/blocked evidence; it is never silently normalised or guessed.
- Record a RED command before behavioural code, a GREEN command afterwards, then refactor and rerun the focused regression.
- Every EU technology subarea is independently addressable and auditable; a combined table is insufficient.
- No issue state changes until fresh source, migration, test, package, browser, audit and independent-review evidence exists.

---

## File structure and interfaces

| File | Responsibility |
|---|---|
| Create `src/etf_cockpit/registry/seed_data05.py` | immutable expected seed definitions and static count validation |
| Create `src/etf_cockpit/registry/seed_verification.py` | source retrieval, expected/observed discrepancy ledger and evidence checksums |
| Create `src/etf_cockpit/registry/corporate_events.py` | dated predecessor/successor security relationship including ExxonMobil |
| Modify registry models or `data/universe_store.py:1-102` | schema-versioned stable `coverage_area`, `subarea_id`, coverage band, market-cap provenance and alias fields |
| Modify `core/config.py:1-308`, provider mappings, Data Health, audit export and instrument workspace resolver | compatibility config, selected refresh and visible coverage |
| Create `tests/registry/test_data05_seed_schema.py`, `test_data05_verification.py`, `test_data05_corporate_events.py`, `tests/ui/test_data05_subareas_ui.py` | all 39/25/8-9-8, provider, routing and export behaviour |

**Interfaces:**

```python
class SeedVerificationResult(BaseModel):
    instrument_id: str
    expected: dict[str, str]
    observed: dict[str, str | None]
    source_url: str
    retrieved_at: datetime
    result: Literal["verified", "discrepant", "unavailable", "blocked"]
    evidence_checksum: str

class MarketCapObservation(BaseModel):
    instrument_id: str
    current_market_cap_local: Decimal | None
    current_market_cap_eur: Decimal | None
    market_cap_as_of: datetime | None
    market_cap_source_id: str | None
    market_cap_method: str | None
    current_market_cap_band: str | None

def validate_data05_seed_set(records: Sequence[SeedRecord]) -> Data05ValidationReport: ...
```

### Task 1: Create the immutable 39-exposure seed contract and schema migration

**Files:**

- Create: `src/etf_cockpit/registry/seed_data05.py`, `tests/registry/test_data05_seed_schema.py`
- Modify: registry models or `data/universe_store.py:1-102`, `core/config.py:1-308`, `configs/closure_matrix.yaml`

**Consumes:** Wave 2 canonical registry or its explicitly versioned compatibility adapter.

**Produces:** a single expected seed source with 14 NVIDIA/energy entries and 25 EU technology entries.

- [ ] **Step 1: Write RED cardinality and invariant tests**

```python
def test_required_seed_set_has_exact_coverage_cardinality() -> None:
    report = validate_data05_seed_set(DATA05_SEEDS)
    assert report.canonical_exposure_count == 39
    assert report.eu_technology_count == 25
    assert report.coverage_balance_counts == {"large": 8, "mid": 9, "small": 8}

def test_market_cap_change_cannot_change_identity_or_curation_band() -> None:
    after = apply_market_cap_observation(asml_seed, changed_market_cap)
    assert after.instrument_id == asml_seed.instrument_id
    assert after.subarea_id == "eu_technology/asml"
    assert after.coverage_balance_band == "large"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_data05_seed_schema.py -q`

Expected: FAIL because the DATA-05 seed/schema contract does not exist.

- [ ] **Step 3: Implement expected seed definitions and backward-compatible fields**

Include every table field from DATA-05.3 and DATA-05.3B: canonical ID, issuer/security, provider symbol, venue/MIC, currency, ISIN expected value, class, group/tier, alias relationship, `coverage_area`, `subarea_id`, `coverage_balance_band`, and separate dated current-market-cap fields. Reject duplicate `subarea_id`, duplicate current economic exposure and invalid coverage count before any commit.

- [ ] **Step 4: Run GREEN plus existing universe regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_data05_seed_schema.py tests\test_universe_store.py tests\test_schema_migrations.py -q`

Expected: PASS, with legacy universe compatibility still readable.

- [ ] **Step 5: Record schema-version evidence**

Write the seed definition checksum and a schema migration report listing every new field to `evidence/data05/seed_schema/`.

### Task 2: Build current official/source verification and discrepancy recording

**Files:**

- Create: `src/etf_cockpit/registry/seed_verification.py`, `tests/registry/test_data05_verification.py`, fixture cache directory under `tests/fixtures/data05/`
- Modify: provider/source evidence policies, session/audit event registration

**Consumes:** Task 1 expected seed definitions and Wave 4 source-object contract when available; until then uses immutable local evidence files plus checksums.

**Produces:** one source URL/retrieval/checksum/expected/observed result per seed field and bounded provider probe record.

- [ ] **Step 1: Write RED verification-result tests**

```python
def test_discrepant_official_identifier_blocks_automatic_installation() -> None:
    result = compare_seed_observation(asml_seed, {"isin": "WRONG"}, source_url="https://official.example")
    assert result.result == "discrepant"
    assert result.instrument_id == "asml_xams"

def test_provider_probe_wrong_currency_blocks_score_eligibility() -> None:
    result = verify_provider_probe(eqnr_seed, quote(name="Equinor ASA", currency="USD", exchange="OSE"))
    assert result.score_eligible is False
    assert result.status == "blocked"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_data05_verification.py -q`

Expected: FAIL because verification results and provider-probe comparison do not exist.

- [ ] **Step 3: Implement official evidence collection with deterministic capture**

For every seed, retrieve the issuer first, then official venue/regulator, then current ISO MIC, then a bounded provider response. Store expected field, observed field, source URL, retrieval time, result and SHA-256 evidence checksum. A failed source lookup is `unavailable`, not verified. Never persist secrets or full provider payloads.

- [ ] **Step 4: Run GREEN and fixture/live separation**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_data05_verification.py -q`

Expected: PASS using deterministic fixtures. Run live official verification as `live_informational` separately; store sources, outcome and retrieval date without making the normal suite depend on internet access.

- [ ] **Step 5: Create the required verification manifest**

Write `evidence/data05/seed_verification_manifest.json` with one result for every instrument/identifier/venue/provider field. Any discrepancy remains visible and blocks seed installation until corrected transparently.

### Task 3: Model listings, share classes, ADRs and ExxonMobil’s dated successor relationship

**Files:**

- Create: `src/etf_cockpit/registry/corporate_events.py`, `tests/registry/test_data05_corporate_events.py`
- Modify: registry relationship model/repository and compatibility identity export

**Consumes:** Tasks 1-2 verified seed records.

**Produces:** explicit predecessor/successor, ADR/secondary listing and share-class relationships that prevent duplicate economic exposures.

- [ ] **Step 1: Write RED relationship tests**

```python
def test_exxon_predecessor_and_successor_share_ticker_without_erasing_history() -> None:
    graph = build_data05_relationship_graph()
    predecessor, successor = graph.security_for("XOM", date(2026, 7, 1)), graph.security_for("XOM", date(2026, 7, 3))
    assert predecessor.isin == "US30231G1022"
    assert successor.isin == "US30233Q1085"
    assert predecessor.security_id != successor.security_id

def test_petr4_and_petr3_remain_distinct_share_classes() -> None:
    assert relationship_graph.security_id_for("PETR4") != relationship_graph.security_id_for("PETR3")
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_data05_corporate_events.py tests\registry\test_registry_relationships.py -q`

Expected: FAIL because no dated successor and relationship records exist.

- [ ] **Step 3: Implement dated relationship records**

Create one-for-one successor evidence for ExxonMobil, secondary/ADR aliases for Equinor, Shell, bp, TotalEnergies, CNQ, ASML, SAP, Nokia, Ericsson and STMicroelectronics, plus explicit preferred/H-share/class relationships for Petrobras, PetroChina and Sinopec. Default membership contains only one canonical economic exposure unless the user explicitly creates another membership.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_data05_corporate_events.py tests\registry\test_registry_relationships.py tests\registry\test_data05_seed_schema.py -q`

Expected: PASS; historical identity remains date-valid and duplicate current rows are rejected.

- [ ] **Step 5: Emit corporate-event audit extract**

Export `evidence/data05/corporate_events.json` with IDs, valid dates, source refs and checksums.

### Task 4: Stage, verify and commit the all-or-nothing DATA-05 universe revision

**Files:**

- Create: `tests/registry/test_data05_seed_installation.py`
- Modify: registry/universe service, provider selection API and audit manifest builder

**Consumes:** Tasks 1-3 validation results.

**Produces:** one revision-protected seed generation with all 39 records, or no active DATA-05 generation if any required seed is blocked.

- [ ] **Step 1: Write RED atomic/revision tests**

```python
def test_one_blocked_required_seed_keeps_active_generation_unchanged() -> None:
    before = repository.current_generation().generation_id
    report = install_data05_seeds(repository, verification_results=one_blocked_seed)
    assert report.committed is False
    assert repository.current_generation().generation_id == before

def test_reapplying_verified_seed_set_is_idempotent() -> None:
    first = install_data05_seeds(repository, verification_results=all_verified)
    second = install_data05_seeds(repository, verification_results=all_verified)
    assert second.generation_id == first.generation_id
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_data05_seed_installation.py tests\test_universe_store.py -q`

Expected: FAIL because no seed installation service or all-or-nothing policy exists.

- [ ] **Step 3: Implement staged installer using expected revision**

`install_data05_seeds()` validates all expected verification results, stable IDs, group membership, canonical listing/alias graph and 8/9/8 count before calling the existing expected-revision save/generation commit. It emits the specified `universe_seed_*`, `provider_alias_validated`, `security_successor_linked` and `market_cap_band_*` events.

- [ ] **Step 4: Run GREEN and targeted refresh guard**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_data05_seed_installation.py tests\registry\test_data05_seed_schema.py tests\test_universe_store.py -q`

Expected: PASS; save does not fetch all prices or trigger TimesFM/Toto and refresh selection includes only requested IDs.

- [ ] **Step 5: Save revision/manifest evidence**

Capture active universe revision, content checksum, validation report and evidence manifest references in `evidence/data05/install/`.

### Task 5: Deliver all EU technology subareas, coverage screens and audit paths

**Files:**

- Create: `src/etf_cockpit/app/selectors/entity_workspace.py`, `tests/ui/test_data05_subareas_ui.py`, `tests/ui/test_data05_universe_ui.py`
- Modify: `app/router.py:1-182`, `app/pages/universe_manager.py`, `app/pages/instrument_detail.py`, Data Health, Provider Status and audit export code

**Consumes:** Task 4 committed seed generation and Wave 1 gate/report view models.

**Produces:** stable deep links for 25 individually resolvable EU technology entity subareas and exported 25-row audit proof.

- [ ] **Step 1: Write RED route and coverage tests**

```python
@pytest.mark.parametrize("seed", EU_TECH_SEEDS, ids=lambda seed: seed.instrument_id)
def test_each_eu_technology_subarea_resolves_independently(seed: SeedRecord) -> None:
    route = entity_subarea_route(seed.subarea_id)
    view = build_entity_workspace(route, state)
    assert view.instrument_id == seed.instrument_id
    assert view.subarea_id == seed.subarea_id

def test_audit_manifest_contains_exact_8_9_8_split() -> None:
    manifest = build_data05_audit_manifest(registry)
    assert manifest.coverage_balance_counts == {"large": 8, "mid": 9, "small": 8}
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_data05_subareas_ui.py tests\ui\test_data05_universe_ui.py -q`

Expected: FAIL because subarea routes, entity resolver and audit rows do not exist.

- [ ] **Step 3: Implement route-based reusable entity workspace**

Register one route template which resolves `subarea_id` to canonical instrument ID. Render real identity/listing, gate, data-health, official evidence, score/risk/model/portfolio context or explicit unavailable state. The Universe page adds group/coverage filters without 25 top-level navigation entries.

- [ ] **Step 4: Run GREEN, source smoke and package journey**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_data05_subareas_ui.py tests\ui\test_data05_universe_ui.py tests\registry\test_data05_seed_schema.py -q`

Expected: PASS. Then run source and packaged browser journeys for one energy seed from each required venue region and large/mid/small EU technology seed across XAMS, XETR, XPAR, XHEL, XSTO, XMAD and XMIL.

- [ ] **Step 5: Complete dedicated DATA-05 review package**

The reviewer receives the seed verification manifest, all-39 and all-25 assertions, 8/9/8 audit manifest, corporate-event evidence, source/package screenshots, deep-link report and proof that model weights, research thresholds, portfolio targets and execution authority did not change.
