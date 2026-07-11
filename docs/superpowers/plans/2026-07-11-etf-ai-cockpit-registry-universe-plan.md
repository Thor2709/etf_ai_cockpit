# Registry, Classification, Universe and Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` with a fresh implementer and a fresh reviewer for each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `DATA-01` through `DATA-04` by evolving the revision-protected flat universe store into a canonical issuer-security-listing registry with classification, collections, controlled CRUD and separate discovery staging.

**Architecture:** `data/universe_store.py` remains the migration nucleus and atomic/revision semantics remain mandatory. The new registry owns canonical generations while a compatibility adapter continues producing `UniverseRecord` and `ETFConfig` until consumers are migrated.

**Tech Stack:** Python 3.13, Pydantic, UUID, PyArrow, DuckDB, existing atomic I/O, requests, Flet, pytest and Hypothesis.

## Global Constraints

- No scope drift; do not create broker, order, credential or external-upload functionality.
- Evidence, analysis, research state, portfolio review and user decisions stay separate; `execution_allowed` remains `false`.
- Preserve the revision-protected universe store, atomic I/O/recovery, Data Health, provider/evidence contracts, source-aware score eligibility, session trace, audit manifests, router and Flet shell.
- Use narrow adapters and migrations; do not perform unrelated refactoring.
- Do not initialise Git, create a worktree, commit, push, create a pull request, delete user data or modify a remote service.
- Tests must prove observable behaviour and failure paths; one mock-call assertion is insufficient.
- Record a RED command before behavioural code, a GREEN command afterwards, then refactor and rerun the focused regression.
- Visible Flet changes reuse the existing dark research-cockpit vocabulary and expose semantic, keyboard and state behaviour.
- No issue state changes until fresh source, migration, test, package, browser, audit and independent-review evidence exists.
- Store task reports in the progress ledger, `RUN_STATE.json`, `.ai_worklog` and the closure matrix only after evidence exists.

---

## File structure and interfaces

| File | Responsibility |
|---|---|
| Create `src/etf_cockpit/registry/models.py`, `repository.py`, `generation.py`, `migrations.py`, `validators.py`, `resolver.py`, `conflicts.py`, `overrides.py`, `impact.py` | typed identity graph, generations, validation, history and impact |
| Create `src/etf_cockpit/classification/*.py` | two-axis classification, taxonomy, crosswalks and support matrix |
| Create `src/etf_cockpit/universe/*.py` | collection/membership/watchlist/provider policy/import/export services |
| Create `src/etf_cockpit/discovery/*.py` | separate candidate snapshots, filters and promotion workflow |
| Modify `src/etf_cockpit/data/universe_store.py:1-102`, `core/config.py:1-308`, `data/instrument_identity.py`, `data/trade_candidate_analysis.py`, `services.py`, score/portfolio/evidence key adapters | compatibility bridge and downstream stable-ID migration |
| Modify `app/pages/universe_manager.py`, `app/router.py` | controlled registry/universe/discovery surfaces |
| Create `configs/registry_policy.yaml`, `identity_source_policy.yaml`, `classification_taxonomy.yaml`, `classification_crosswalks.yaml`, `analytical_support_matrix.yaml`, `universe_collections.yaml`, `discovery_profiles.yaml` | versioned policies with checksums |

**Interfaces produced:**

```python
class RegistryRepository(Protocol):
    def stage_generation(self, change: RegistryChange, expected_revision: str) -> StagedRegistryGeneration: ...
    def commit_generation(self, staged: StagedRegistryGeneration) -> RegistryGeneration: ...
    def current_generation(self) -> RegistryGeneration: ...

class ResolvedClassification(BaseModel):
    subject_id: UUID
    instrument_kind: str
    asset_class: str
    sector: str | None
    specialist_flags: list[str]
    support_status: str
    analytical_template: str | None

def resolve_discovery_promotion(candidate_id: UUID, decision: PromotionDecision) -> RegistryGeneration: ...
```

### Task 1: Create the registry graph, local validators and generation commit seam

**Files:**

- Create: `src/etf_cockpit/registry/models.py`, `validators.py`, `repository.py`, `generation.py`, `tests/registry/test_models.py`, `tests/registry/test_isin_validator.py`, `tests/registry/test_lei_validator.py`, `tests/registry/test_mic_validator.py`, `tests/registry/test_registry_generation.py`
- Modify: `src/etf_cockpit/data/universe_store.py:1-102`, `src/etf_cockpit/core/config.py:1-308`

**Consumes:** Wave 0 transaction/recovery contract and Wave 1 identity gate codes.

**Produces:** separate issuer, security, listing, provider symbol, alias, source assertion and membership records behind a generation repository.

- [ ] **Step 1: Write RED validator and relationship tests**

```python
def test_two_listings_can_share_one_security_without_provider_symbol_collision() -> None:
    security = SecurityRecord.new(canonical_name="Example ordinary share", isin="US0378331005")
    first = ListingRecord.new(security_id=security.security_id, local_ticker="EXA", operating_mic="XNYS", trading_currency="USD")
    second = ListingRecord.new(security_id=security.security_id, local_ticker="EXA", operating_mic="XLON", trading_currency="GBP")
    assert first.security_id == second.security_id

def test_placeholder_isin_becomes_unresolved_not_an_identifier() -> None:
    assert normalise_isin("needs_verification") is None
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_models.py tests\registry\test_isin_validator.py tests\registry\test_mic_validator.py tests\registry\test_registry_generation.py -q`

Expected: FAIL because the graph and validators do not exist.

- [ ] **Step 3: Implement the graph and atomic generation service**

Create opaque persisted UUIDs, local ISIN/LEI/MIC validators, referential checks and a generation manifest. The repository uses the Wave 0 grouped atomic write and expected revision; it never writes YAML/CSV as co-authoritative runtime state.

- [ ] **Step 4: Run GREEN plus current compatibility tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_models.py tests\registry\test_isin_validator.py tests\registry\test_lei_validator.py tests\registry\test_mic_validator.py tests\registry\test_registry_generation.py tests\test_universe_store.py -q`

Expected: PASS, with existing `UniverseRecord` compatibility loads still working.

- [ ] **Step 5: Capture a registry schema manifest**

Write field dictionary, schema version, generation manifest and validation result to `evidence/registry/schema/`.

### Task 2: Migrate primary YAML and candidate CSV once, preserving aliases and history

**Files:**

- Create: `src/etf_cockpit/registry/migrations.py`, `tests/registry/test_registry_migration.py`, `tests/registry/test_registry_relationships.py`, `tests/registry/test_registry_conflicts.py`
- Modify: `core/config.py:1-308`, `data/instrument_identity.py`, `data/trade_candidate_analysis.py`, `services.py`, score/forecast/portfolio compatibility readers

**Consumes:** Task 1 generation repository.

**Produces:** dry-run report, immutable legacy crosswalk and compatibility registry view.

- [ ] **Step 1: Write RED migration tests against an isolated copy of current sources**

```python
def test_current_59_rows_migrate_once_and_placeholder_isins_are_null() -> None:
    report = plan_legacy_universe_migration(universe_yaml, candidate_csv)
    assert report.input_row_count == 59
    assert report.placeholder_isin_count == 5
    assert report.errors == []

def test_second_migration_is_idempotent() -> None:
    first = migrate_legacy_universe(fixture_root)
    second = migrate_legacy_universe(fixture_root)
    assert second.generation.content_checksum == first.generation.content_checksum
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_registry_migration.py tests\registry\test_registry_relationships.py tests\registry\test_registry_conflicts.py -q`

Expected: FAIL because no graph migration/report/crosswalk exists.

- [ ] **Step 3: Implement staged migration and compatibility adapter**

The migration creates issuer/security/listing/provider/membership assertions, records unresolved identifiers and writes `legacy_instrument_id → issuer_id/security_id/listing_id/preferred_alias` crosswalk. The `UniverseRecord` view is generated from committed registry data; normal workflows stop reading the candidate CSV directly.

- [ ] **Step 4: Run GREEN and downstream reconciliation**

Run: `.\.venv\Scripts\python.exe -m pytest tests\registry\test_registry_migration.py tests\registry\test_registry_relationships.py tests\test_instrument_identity.py tests\test_simple_scores.py -q`

Expected: PASS; no current alias/provider mapping is lost and downstream fixtures resolve stable listing IDs.

- [ ] **Step 5: Generate dry-run and rollback evidence**

Store `migration_report.json`, crosswalk checksum, row counts, unresolved/conflict extract and rollback result under `evidence/registry/migration/`.

### Task 3: Resolve two-axis classification and support routing without a stock fallback

**Files:**

- Create: `src/etf_cockpit/classification/models.py`, `taxonomy.py`, `crosswalks.py`, `resolver.py`, `support_matrix.py`, `tests/classification/test_resolver.py`, `tests/classification/test_support_matrix.py`, `tests/classification/test_taxonomy.py`
- Modify: `data/trade_candidate_analysis.py`, `signals/simple_scores.py:133-1989`, `signals/strategy_templates.py`, `configs/analytical_support_matrix.yaml`

**Consumes:** Task 1 identity assertions and Wave 1 authority gate API.

**Produces:** immutable `ResolvedClassification` records with support status/template and no implicit common-stock route.

- [ ] **Step 1: Write RED template-routing tests**

```python
def test_unknown_instrument_never_defaults_to_general_equity() -> None:
    resolution = resolve_classification(unresolved_security, assertions=[])
    assert resolution.support_status == "manual_review"
    assert resolution.analytical_template is None

def test_savings_bank_equity_certificate_selects_specialist_template() -> None:
    resolution = resolve_classification(sparebanken_security, assertions=bank_assertions)
    assert resolution.analytical_template == "bank_equity_certificate"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\classification\test_resolver.py tests\classification\test_support_matrix.py tests\test_simple_scores.py -q`

Expected: FAIL because existing candidate logic falls back to stock-like treatment.

- [ ] **Step 3: Implement source-precedence classification resolution**

Resolve legal structure separately from economic exposure. Preserve source taxonomy/version/confidence, flag conflicts, select support matrix entry and issue a gate effect for unknown, rejected or specialist-incomplete records.

- [ ] **Step 4: Run GREEN and no-fallback regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\classification tests\test_simple_scores.py tests\test_asset_guardrails.py -q`

Expected: PASS; unknown/certificate/unsupported assets cannot receive normal stock scoring.

- [ ] **Step 5: Record classification coverage**

Write `classification_resolution_summary.json`, unresolved/conflicted extract and support-matrix checksum to `evidence/registry/classification/`.

### Task 4: Create revisioned collections, provider policies and a controlled Universe Manager

**Files:**

- Create: `src/etf_cockpit/universe/collections.py`, `memberships.py`, `watchlists.py`, `imports.py`, `exports.py`, `tests/universe/test_collections.py`, `tests/universe/test_memberships.py`, `tests/universe/test_universe_import.py`, `tests/universe/test_revision_conflicts.py`
- Modify: `app/pages/universe_manager.py:1-end`, `app/router.py:1-182`, `data/universe_store.py:1-102`, provider config adapters

**Consumes:** Tasks 1-3 registry, classification and generation APIs.

**Produces:** one manager for collections/watchlists/listing-scoped provider policies, impact preview and revision-aware commits.

- [ ] **Step 1: Write RED CRUD/revision tests**

```python
def test_remove_membership_does_not_delete_listing() -> None:
    service.remove_membership(membership_id, expected_revision=revision)
    assert repository.get_listing(listing_id) is not None
    assert repository.get_membership(membership_id) is None

def test_stale_edit_returns_field_level_revision_conflict() -> None:
    with pytest.raises(UniverseRevisionConflict, match="provider_symbol"):
        service.update_provider_policy(change, expected_revision="old")
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\universe\test_collections.py tests\universe\test_memberships.py tests\universe\test_revision_conflicts.py -q`

Expected: FAIL because current Universe page has no service-backed CRUD/impact preview.

- [ ] **Step 3: Implement service-first mutation and Flet edit workflow**

Pages call a manager service only. Each save creates a new generation, shows identity/classification/membership/provider policy impact and never starts a refresh, score or forecast job. Protected primary/secondary/Sparebanken collections cannot be silently deleted.

- [ ] **Step 4: Run GREEN plus UI component suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests\universe tests\test_universe_store.py tests\test_onboarding.py -q`

Expected: PASS, including import dry-run, interrupted commit, rollback and no-auto-workflow behaviour.

- [ ] **Step 5: Capture UI/revision evidence**

Record source/package journeys for add, edit, disable, remove membership, watchlist and conflict reload; export the impact and revision manifests.

### Task 5: Keep discovery separate until explicit promotion

**Files:**

- Create: `src/etf_cockpit/discovery/models.py`, `connectors.py`, `pipeline.py`, `filters.py`, `promotion.py`, `snapshots.py`, `tests/discovery/test_filters.py`, `tests/discovery/test_snapshots.py`, `tests/discovery/test_promotion.py`
- Modify: scope resolver, Data Health source inventory and router/Universe UI links

**Consumes:** Tasks 1-4 canonical registry and collections.

**Produces:** source-dated discovery candidates, profiles and promotion flow that cannot enter a monitored scope accidentally.

- [ ] **Step 1: Write RED promotion and point-in-time tests**

```python
def test_unpromoted_candidate_is_excluded_from_monitored_scope() -> None:
    snapshot = run_discovery(profile, source_rows=[candidate])
    assert candidate.discovery_candidate_id not in resolve_monitored_listing_ids()

def test_ambiguous_identity_blocks_promotion() -> None:
    with pytest.raises(PromotionBlocked, match="identity"):
        promote_candidate(ambiguous_candidate, destination_collection=secondary)
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\discovery\test_filters.py tests\discovery\test_snapshots.py tests\discovery\test_promotion.py -q`

Expected: FAIL because candidate CSV remains a direct analysis input rather than separate staging.

- [ ] **Step 3: Implement immutable snapshot/profile/promotion records**

Store source checksum, source as-of, profile checksum, market-cap/liquidity provenance and pass/fail reasons. Promotion delegates to the Task 4 registry service only after identity, classification, provider and liquidity gates pass or have an explicit reviewed waiver.

- [ ] **Step 4: Run GREEN and scope regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\discovery tests\test_two_tier_workflow.py tests\test_asset_guardrails.py -q`

Expected: PASS; discovery never changes monitored membership or starts a workflow without an explicit promotion.

- [ ] **Step 5: Submit the registry wave for independent review**

The reviewer checks identifier state, crosswalk, no-default-stock path, CRUD revision/rollback, discovery separation and required evidence artefacts before Wave 3 starts.
