# Storage, Point-in-Time and Official Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` with a fresh implementer and a fresh reviewer for each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `STORE-01` through `STORE-04` and `EVID-01` through `EVID-05` with a persistent catalogue over canonical Parquet, source-object/temporal lineage, official evidence acquisition, citation-grade facts/events and constrained data exploration/export.

**Architecture:** Promote the current small DuckDB helper behind a catalogue repository without replacing Parquet or Data Health. Source acquisition, parsing, normalisation and derivation remain separate and produce immutable generations through the Wave 0 transaction primitive.

**Tech Stack:** DuckDB, PyArrow, Pydantic, requests, Arelle, defusedxml, PDF parser, feedparser, Flet, pytest and Playwright/Chrome.

## Global Constraints

- No scope drift; do not create broker, order, credential or external-upload functionality.
- Evidence, analysis, research state, portfolio review and user decisions stay separate; `execution_allowed` remains `false`.
- Preserve the revision-protected universe store, atomic I/O/recovery, Data Health, provider/evidence contracts, source-aware score eligibility, session trace, audit manifests, router and Flet shell.
- Use narrow adapters and migrations; do not perform unrelated refactoring.
- Do not initialise Git, create a worktree, commit, push, create a pull request, delete user data or modify a remote service.
- Current official sources, provider terms, rate policy and identity evidence must be recorded; fixture tests remain deterministic and live tests are informational.
- Test parser safety, unavailable/conflict state, revision and failure paths rather than only transport mocks.
- Record a RED command before behavioural code, a GREEN command afterwards, then refactor and rerun the focused regression.
- Visible Flet changes reuse the existing dark research-cockpit vocabulary and expose semantic, keyboard and state behaviour.
- No issue state changes until fresh source, migration, test, package, browser, audit and independent-review evidence exists.

---

## File structure and interfaces

| File | Responsibility |
|---|---|
| Create `src/etf_cockpit/storage/models.py`, `catalogue.py`, `generations.py`, `writer.py`, `reader.py`, `temporal.py`, `lineage.py`, `query_service.py`, `source_objects.py`, `exports.py` | catalogue, temporal/lineage schema, current/as-of reads and safe exports |
| Modify `data/duckdb_store.py:1-60`, `data/health.py`, `data/export_tables.py` | compatibility facade, catalogue-backed Data Health/export |
| Create `src/etf_cockpit/evidence/*.py` | provider/capability source authority, documents, citations, extraction review and events |
| Adapt `data/sec_edgar_provider.py`, `data/esef_provider.py`, `data/fund_documents.py`, `data/fund_holdings.py`, `data/news_context.py`, parser modules | concrete acquisition/parser adapters behind evidence contracts |
| Create policies in `configs/` | storage/dataset/availability/query/export/provider/authority/terms/freshness policies |
| Create Data Catalogue/Data Explorer/evidence pages | catalogue-backed drill-down and citation review without folder traversal |

**Interfaces:**

```python
class CatalogueRepository(Protocol):
    def current_generation(self, dataset_id: str) -> DatasetGeneration | None: ...
    def register_generation(self, staged: ValidatedGeneration) -> DatasetGeneration: ...
    def rollback_to(self, dataset_id: str, generation_id: str) -> DatasetGeneration: ...
    def resolve_view(self, dataset_id: str, as_of: datetime | None = None) -> str: ...

class EvidenceCitation(BaseModel):
    document_id: str
    source_object_checksum: str
    locator: str
    excerpt: str
    available_at: datetime | None

def query_current_or_asof(dataset_id: str, *, as_of_time: datetime | None, filters: Mapping[str, object]) -> DataFrame: ...
```

### Task 1: Establish the persistent DuckDB catalogue and generation views

**Files:**

- Create: `src/etf_cockpit/storage/models.py`, `catalogue.py`, `generations.py`, `tests/storage/test_catalogue.py`, `tests/storage/test_generations.py`, `tests/storage/test_schemas.py`
- Modify: `src/etf_cockpit/data/duckdb_store.py:1-60`, `configs/dataset_registry.yaml`

**Consumes:** Wave 0 atomic transaction and Wave 2 canonical IDs.

**Produces:** logical current/as-of views over committed Parquet generations and a rebuildable local `cockpit_catalogue.duckdb`.

- [ ] **Step 1: Write RED transaction/view tests**

```python
def test_current_view_never_exposes_staged_rows_after_interrupted_commit(tmp_path: Path) -> None:
    catalogue = CatalogueRepository.open(tmp_path)
    old = register_fixture_generation(catalogue, values=[1])
    with inject_commit_failure("after_file_manifest"):
        stage_and_register(catalogue, values=[2])
    assert catalogue.query_current("prices").to_dict("list") == {"value": [1]}

def test_catalogue_rebuild_uses_generation_manifests_only(tmp_path: Path) -> None:
    rebuilt = rebuild_catalogue_from_manifests(tmp_path)
    assert rebuilt.current_generation("prices").content_checksum == expected_checksum
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\storage\test_catalogue.py tests\storage\test_generations.py tests\storage\test_schemas.py -q`

Expected: FAIL because current `duckdb_store.py` only creates per-query in-memory connections.

- [ ] **Step 3: Implement catalogue repository and compatibility facade**

Create catalogue metadata tables, staged/validated/committed generation states, file manifests, current pointer and views. The existing helper delegates to `CatalogueRepository` after current-view parity tests pass. No UI or domain module gains arbitrary file-path access.

- [ ] **Step 4: Run GREEN and existing data-health regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\storage\test_catalogue.py tests\storage\test_generations.py tests\test_data_health.py -q`

Expected: PASS; Data Health displays its current evidence model while reporting catalogue divergence when a legacy path remains.

- [ ] **Step 5: Save catalogue inventory**

Write `evidence/storage/catalogue_inventory.json`, schema SQL, generation manifest samples and rebuild checksum results.

### Task 2: Enforce temporal, source-object, layer and lineage contracts

**Files:**

- Create: `storage/temporal.py`, `source_objects.py`, `lineage.py`, `quality.py`, `tests/storage/test_temporal.py`, `test_source_objects.py`, `test_lineage.py`, `test_quality.py`
- Modify: all migrated data writers through their owner interfaces; `core/atomic_io.py` is consumed, not replaced

**Consumes:** Task 1 catalogue and Wave 0 transaction records.

**Produces:** immutable source objects and temporal source/clean/derived records with current/as-of semantics.

- [ ] **Step 1: Write RED bitemporal and parser-isolation tests**

```python
def test_asof_query_excludes_fact_unavailable_at_decision_time() -> None:
    rows = query_current_or_asof("financial_facts", as_of_time=datetime(2026, 1, 1, tzinfo=UTC), filters={})
    assert all(row.available_at <= datetime(2026, 1, 1, tzinfo=UTC) for row in rows.itertuples())

def test_parser_accepts_source_object_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(requests, "get", pytest.fail)
    assert parse_sec_source_object(source_object).records
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\storage\test_temporal.py tests\storage\test_source_objects.py tests\storage\test_lineage.py tests\storage\test_quality.py -q`

Expected: FAIL because availability, source object and lineage contracts are not universal.

- [ ] **Step 3: Implement profile-driven temporal/source/layer validation**

Every migrated dataset declares primary and temporal keys, source object checksum, `available_at` rule/version, schema/quality status and upstream generation list. A revision appends/supersedes; it never overwrites. Parse functions accept local bytes/path/source ID and make no network call.

- [ ] **Step 4: Run GREEN plus no-lookahead regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\storage\test_temporal.py tests\storage\test_source_objects.py tests\storage\test_lineage.py tests\test_no_lookahead.py -q`

Expected: PASS, including timezone, restatement, late-arrival and malicious XML/source fixtures.

- [ ] **Step 5: Capture lineage and quarantine evidence**

Generate source-to-derived lineage coverage, quarantine summary and temporal policy checksum in `evidence/storage/lineage/`.

### Task 3: Create constrained query, explorer and export services

**Files:**

- Create: `storage/query_service.py`, `search_index.py`, `exports.py`, `tests/storage/test_query_service.py`, `test_search_index.py`, `test_exports.py`
- Create: `app/pages/data_explorer.py`, `tests/ui/test_data_catalogue_ui.py`, `tests/ui/test_data_explorer_ui.py`
- Modify: `data/health.py`, data-health/evidence/instrument pages and router

**Consumes:** Tasks 1-2 catalogue/current-as-of/lineage APIs.

**Produces:** parameterised read-only views, instrument timeline, safe export profiles and LLM retrieval request boundary.

- [ ] **Step 1: Write RED safety/privacy tests**

```python
def test_query_service_rejects_file_escape_and_write_sql() -> None:
    with pytest.raises(QueryBlocked):
        execute_approved_query("COPY (SELECT 1) TO 'C:/escape.csv'")

def test_default_export_excludes_private_journal_text() -> None:
    bundle = export_profile("instrument_review", include_private=False)
    assert "secret thesis" not in bundle.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\storage\test_query_service.py tests\storage\test_exports.py tests\ui\test_data_explorer_ui.py -q`

Expected: FAIL because pages still depend on scattered physical paths and no constrained query/export profile exists.

- [ ] **Step 3: Implement allow-listed parameterised retrieval and export manifests**

Expose current/as-of dataset browser, timeline and retrieval request APIs with row/time/byte limits. The advanced query compiler accepts only selected views, selected columns, filters, grouping, sort and limit; it rejects DDL, `COPY`, `ATTACH`, `INSTALL`, arbitrary file functions and non-SELECT commands.

- [ ] **Step 4: Run GREEN and UI accessibility tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\storage\test_query_service.py tests\storage\test_search_index.py tests\storage\test_exports.py tests\ui\test_data_catalogue_ui.py tests\ui\test_data_explorer_ui.py -q`

Expected: PASS; exports have generation/query/checksum manifests and the UI shows partial/unavailable data honestly.

- [ ] **Step 5: Save explorer evidence**

Store query allow-list, pagination/safety results, export manifests and source/package screenshots under `evidence/storage/explorer/`.

### Task 4: Formalise provider capability, field authority and document registry

**Files:**

- Create: `evidence/models.py`, `provider_registry.py`, `document_registry.py`, `citations.py`, `coverage.py`, `tests/evidence/test_provider_registry.py`, `test_source_authority.py`, `test_document_registry.py`, `test_citations.py`
- Modify: `data/provider_registry.py:1-59`, `data/trust_artifacts.py:1-943`, provider status/evidence pages and audit export

**Consumes:** Tasks 1-3 catalogue/source-object interfaces and Wave 2 issuer/security/listing IDs.

**Produces:** the sole provider/capability/authority/terms/health registry and exact-version document/citation identity.

- [ ] **Step 1: Write RED precedence/status tests**

```python
def test_lower_authority_provider_cannot_overwrite_official_fact() -> None:
    resolved = resolve_field("ter", [official_kid_assertion, provider_assertion])
    assert resolved.selected_assertion_id == official_kid_assertion.assertion_id

def test_not_implemented_and_offline_are_distinct_capability_states() -> None:
    assert capability_status(not_implemented).status == "not_implemented"
    assert capability_status(network_timeout).status == "offline"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\evidence\test_provider_registry.py tests\evidence\test_source_authority.py tests\evidence\test_document_registry.py tests\evidence\test_citations.py -q`

Expected: FAIL because field-level provider/document resolution is absent.

- [ ] **Step 3: Implement versioned provider/document/citation models**

Provider capabilities include terms, rate/user-agent policy, jurisdiction coverage, freshness and health. Documents link canonical identity, source object, publication/availability timestamps, predecessor/amendment and checksum. Citations resolve exact document locator/excerpt against the matching checksum.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\evidence\test_provider_registry.py tests\evidence\test_source_authority.py tests\evidence\test_document_registry.py tests\evidence\test_citations.py tests\test_provider_registry.py -q`

Expected: PASS; current provider/evidence pages remain compatible and all unavailable categories remain explicit.

- [ ] **Step 5: Export provider/evidence audit registry**

Write provider health, source authority, terms, coverage and document/citation validation summaries to `evidence/evidence/control_plane/`.

### Task 5: Integrate SEC, ESEF, ETF documents and event ingestion through the unified evidence pipeline

**Files:**

- Modify: `data/sec_edgar_provider.py`, `parsers/sec_facts.py`, `data/esef_provider.py`, `parsers/esef_ixbrl.py`, `data/fund_documents.py`, `data/fund_holdings.py`, `parsers/priips_kid.py`, `parsers/index_methodology.py`, `data/rss_provider.py`, `data/news_context.py`
- Create: `evidence/acquisition.py`, `extraction.py`, `review.py`, `events.py`, `tests/evidence/test_sec_edgar.py`, `test_esef_arelle.py`, `test_etf_documents.py`, `test_etf_holdings.py`, `test_events.py`, `test_rss_atom.py`

**Consumes:** Task 4 evidence contract and the existing parser/provider foundations.

**Produces:** source-linked, point-in-time facts/events with parser warnings, review status and visible coverage limitations.

- [ ] **Step 1: Create RED fixtures for source-specific failure paths**

```python
def test_sec_requires_identified_user_agent_before_network_acquisition() -> None:
    result = acquire_sec_filings(cik="0000789019", policy=Policy(user_agent=None))
    assert result.capability_status == "not_configured"

def test_esef_zip_traversal_is_quarantined() -> None:
    outcome = parse_esef_package(malicious_zip_source_object)
    assert outcome.status == "invalid_package"
    assert outcome.records == []

def test_partial_top_holdings_never_claim_full_coverage() -> None:
    holdings = normalise_holdings(top_ten_document)
    assert holdings.coverage < 1
    assert holdings.source_scope == "partial"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\evidence\test_sec_edgar.py tests\evidence\test_esef_arelle.py tests\evidence\test_etf_documents.py tests\evidence\test_events.py -q`

Expected: FAIL where adapters still bypass document/source-object/review contracts.

- [ ] **Step 3: Route each adapter through acquire → source object → parse → normalise → review → commit**

SEC supports selected forms and companyfacts/filing differences; ESEF supports documented jurisdiction/manual package paths and Arelle validation; ETF parsers accept exact ISIN/share class documents and preserve page locators/coverage; RSS/official events preserve canonical URL, version, first-seen, source tier and body policy. Invalid, unavailable, ambiguous or copyright-limited results remain explicit and cannot become authority automatically.

- [ ] **Step 4: Run GREEN, security and UI regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\evidence tests\test_sec_edgar_provider.py tests\test_esef_ixbrl_parser.py tests\test_priips_kid_parser.py tests\test_index_methodology_parser.py tests\test_news_context.py -q`

Expected: PASS using exact fixture checksums. Live acquisitions run separately as informational evidence with rate and terms records.

- [ ] **Step 5: Capture source/package/browser evidence and independent review**

Verify cached/offline source mode, citation open, conflict/review paths, document/event timelines and packaged parser availability. The reviewer checks no official coverage is overstated and no parser output becomes a score authority without the governance gate.
