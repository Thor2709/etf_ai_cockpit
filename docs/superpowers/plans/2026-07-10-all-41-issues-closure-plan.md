# All 41 Open Issues Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended for bounded parser/test tasks) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement, verify and evidence-strictly close the 41 reviewed open issues through one dependency-ordered hands-off closure programme.

**Architecture:** Use eight closure waves over shared workflow, provenance, parser, analytics, UI and audit foundations. Providers acquire immutable raw material, parsers consume local files, normalisers commit versioned clean stores atomically, and UI/export consumers read canonical stores. Existing trust artefacts are extracted and strengthened rather than discarded.

**Tech Stack:** Python 3.13 local runtime with project floor 3.11, Flet/Flet Web, pandas, PyArrow/Parquet, Pydantic, requests, Arelle 2.41 ESEF tooling, pdfplumber 0.11, feedparser, pytest, Hypothesis, Ruff, targeted mypy, Playwright/browser tooling, Chrome and Windows computer use.

## Global Constraints

- Repository root is `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit`.
- The directory is not a Git repository. Do not run `git init` and do not claim commits; every task ends with a durable checkpoint instead.
- Preserve all existing user data. Back up affected stores before schema migrations and verify backup checksums.
- Official public fixtures and vetted parser/testing dependencies are authorised.
- Controlled restructuring, new focused modules, new UI routes and versioned migrations are authorised.
- No destructive deletion, remote publish/upload, secret exposure or broker/trading-authority change.
- No invented financial data or identifiers. Missing, stale, conflicted or unverifiable evidence stays unavailable, `manual_review` or `no_trade`.
- LLMs, models, news and candles cannot override deterministic provenance or risk gates.
- SEC, ESEF/iXBRL, PRIIPs and methodology issues close only with real official fixtures, parser tests, UI workflow, audit/export proof and packaged browser verification.
- Playwright, Chrome, screenshots, visual comparison and Windows computer use are mandatory parts of UI closure evidence.
- Before every major phase transition, update `RUN_STATE.json`, `RUN_LOG.md`, `HANDOFF.md` and the required `.ai_worklog` files.
- If usage ends, stop only after recording the exact next command and first unpassed closure criterion.

---

## Plan-Wide File Structure

**Execution and closure control**

- Create `configs/closure_matrix.yaml`: 41 issue records and criterion-level evidence requirements.
- Create `src/etf_cockpit/core/closure.py`: typed closure records and gate evaluation.
- Create `scripts/closure_status.py`: validate and render closure readiness.
- Create `scripts/dev_finish_check.py`: focused/full/build/browser gate orchestrator.
- Create `RUN_STATE.json`: durable machine-readable resume state.

**Runtime integrity**

- Create `src/etf_cockpit/core/workflow.py`: shared action state/result/error contract.
- Create `src/etf_cockpit/core/atomic_io.py`: validated atomic writes and backups.
- Create `src/etf_cockpit/core/migrations.py`: versioned, idempotent store/config migrations.
- Modify `src/etf_cockpit/core/session_log.py`, `src/etf_cockpit/app/state.py` and dashboard components to use the shared contract.

**Canonical evidence**

- Create `src/etf_cockpit/data/contracts.py`: provider, identity, fact, document, holding, news, conflict and evidence schemas.
- Create `src/etf_cockpit/data/provider_registry.py`.
- Create `src/etf_cockpit/data/instrument_identity.py`.
- Create `src/etf_cockpit/data/source_conflicts.py`.
- Create `src/etf_cockpit/data/evidence_ledger.py`.
- Split corresponding behaviour out of `src/etf_cockpit/data/trust_artifacts.py`, leaving compatibility wrappers during migration.

**Official providers and parsers**

- Create `src/etf_cockpit/parsers/__init__.py`, `contracts.py`, `sec_facts.py`, `esef_ixbrl.py`, `priips_kid.py` and `index_methodology.py`.
- Create `src/etf_cockpit/data/sec_edgar_provider.py`, `esef_provider.py`, `rss_provider.py` and `fred_provider.py`.
- Create `src/etf_cockpit/data/fund_documents.py`, `fund_holdings.py`, `news_context.py` and `fundamentals.py`.
- Create `tests/fixtures/official/manifest.json` and checksummed fixture subdirectories.

**Universe, analytics and operations**

- Create `src/etf_cockpit/data/universe_store.py`, `score_history.py` and `run_changes.py`.
- Create `src/etf_cockpit/features/crowding.py` and `benchmark_attribution.py`.
- Create `src/etf_cockpit/signals/feature_drivers.py` and `friction_edge.py`.
- Create pages `data_health.py`, `universe_manager.py`, `import_export.py`, `errors_recovery.py`, `what_changed.py` and `onboarding.py`.
- Replace `etf_detail.py` with a compatibility wrapper over new `instrument_detail.py` until route tests pass.

**Dependencies and tests**

- Create `requirements-parsers.txt` with `arelle-release[esef]>=2.41.4,<2.42`, `pdfplumber>=0.11.9,<0.12`, `defusedxml>=0.7.1,<0.8` and `feedparser>=6.0.11,<7`.
- Create `requirements-dev.txt` with `pytest>=9,<10`, `hypothesis>=6.140,<7`, `ruff>=0.12,<1`, `mypy>=1.16,<2` and `pytest-timeout>=2.4,<3`.
- Add focused test modules named in the tasks below; update existing tests rather than duplicating coverage.

## Shared Type Catalogue

The following names and fields are fixed across tasks:

- `OfficialFixture`: fixture ID, source URL, retrieval time, SHA-256, document type, authority, entity, period, licence note and relative path.
- `RawDocument`: path, source URL, retrieval time, SHA-256, provider ID, document type, media type and HTTP status.
- `ParseWarning`: code, message, severity and source location.
- `ParseResult[T]`: records, warnings, parser name/version, source SHA-256 and success state.
- `IdentityClaim`: instrument/provider IDs, ISIN, ticker, exchange, MIC, currency, asset type, share class, authority and as-of.
- `IdentityResolution`: canonical identity or `None`, original claims, warnings and manual-review flag.
- `MetricClaim`: instrument, metric, value, unit, period, source ID, authority and as-of.
- `ConflictResolution`: selected claim or `None`, rejected claims, reason, materiality and manual-review flag.
- `EvidenceSource`: source/provider IDs, authority, as-of, freshness, conflict ID, URL and checksum.
- `EvidenceLedgerEntry`: instrument, component, raw metric, normalised score, source ID, authority, as-of, freshness, conflict ID and score eligibility.
- `DataHealthReport`: generation time, health rows, warning count and error count; every row includes dataset, path, schema version, rows, checksum, as-of, freshness, last success/failure and warnings.
- `UniverseSaveResult`: revision, backup manifest, changed IDs and invalidated cache paths; saving never launches refresh/model workflows.
- `ImportPreview` and `RestorePreview`: immutable preview ID, source checksum, validation rows, warnings/errors and proposed destination changes.

Create each dataclass in its owning task and import it elsewhere; do not create parallel dictionaries with alternate field names.

## Execution Protocol

For every task:

1. Write the named failing test first and run it to confirm the expected failure.
2. Implement only the task's declared interfaces and behaviour.
3. Run focused tests and inspect warnings/logs.
4. Run affected integration/browser checks when the task changes a user-facing workflow.
5. Update `RUN_STATE.json` and worklogs before beginning the next task.
6. Ask an independent reviewer at every wave gate; verify review findings locally before applying them.

No issue moves to closed inside an implementation task. Closure occurs only in Task 23 after all issue-specific dossiers and final package/browser gates pass.

---

### Task 1: Baseline Inventory and Machine-Readable Closure Matrix

**Issues:** All 41, evidence inventory only.

**Files:**
- Create: `configs/closure_matrix.yaml`
- Create: `src/etf_cockpit/core/closure.py`
- Create: `scripts/closure_status.py`
- Create: `tests/test_closure_matrix.py`
- Create: `RUN_STATE.json`
- Modify: `RUN_LOG.md`, `HANDOFF.md`, `.ai_worklog/WORKLOG.md`

**Interfaces:**
- Produces `ClosureCriterion`, `IssueClosureRecord`, `load_closure_matrix(path: Path) -> list[IssueClosureRecord]` and `evaluate_issue(record, evidence_root: Path) -> ClosureEvaluation`.
- `ClosureEvaluation.ready` is true only when every required criterion has `source`, `tests`, applicable `ui`, applicable `export`, applicable `build` and applicable `browser` evidence.

- [ ] **Step 1: Write the matrix validation tests**

```python
def test_closure_matrix_contains_exactly_the_reviewed_41_issue_ids():
    records = load_closure_matrix(Path("configs/closure_matrix.yaml"))
    assert len(records) == 41
    assert {record.issue_id for record in records} == EXPECTED_41_IDS

def test_required_gate_cannot_be_marked_ready_without_evidence_file(tmp_path):
    evaluation = evaluate_issue(required_ui_record(), tmp_path)
    assert evaluation.ready is False
    assert "ui" in evaluation.missing_gates
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_closure_matrix.py -q`  
Expected: import failure because `core.closure` and the matrix do not exist.

- [ ] **Step 3: Implement the exact closure contracts**

```python
@dataclass(frozen=True)
class ClosureCriterion:
    criterion_id: str
    text: str
    required_gates: tuple[str, ...]
    evidence_paths: tuple[str, ...] = ()

@dataclass(frozen=True)
class IssueClosureRecord:
    issue_id: str
    title: str
    wave: int
    criteria: tuple[ClosureCriterion, ...]

@dataclass(frozen=True)
class ClosureEvaluation:
    issue_id: str
    ready: bool
    missing_gates: tuple[str, ...]
    evidence_paths: tuple[str, ...]
```

Populate all acceptance criteria from `issues/open.md`; do not collapse multiple bullets into one vague criterion. Initialise evidence paths empty and status `still_open`.

- [ ] **Step 4: Capture the real baseline**

Run:

```powershell
git status --short
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pytest --collect-only -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q scripts src tests
.\.venv\Scripts\python.exe scripts\run_app.py --smoke
```

Expected: Git reports no repository; Python is 3.13; 131 or more tests collect; tests, compile and smoke exit 0 before feature edits.

- [ ] **Step 5: Write the first durable checkpoint**

Set `RUN_STATE.json` to wave 1/task 1 complete with exact command outputs, current test count and `next_command` for Task 2. Append the same facts to `RUN_LOG.md` and `.ai_worklog/TESTING.md`.

---

### Task 2: Dependency, Licence and Official Fixture Foundation

**Issues:** `UPDATEV2-0012`, `UPDATEV2-0013`, `UPDATEV2-0017`, `UPDATEV2-0019`, `ISSUE-0025`, `ISSUE-0055` foundations.

**Files:**
- Create: `requirements-parsers.txt`, `requirements-dev.txt`, `src/etf_cockpit/parsers/__init__.py`, `src/etf_cockpit/parsers/contracts.py`
- Modify: `pyproject.toml`, `scripts/build_windows.bat`
- Create: `tests/fixtures/official/manifest.json`
- Create: `tests/test_official_fixture_manifest.py`
- Modify: `REPORT.md`, `.ai_worklog/DECISIONS.md`

**Interfaces:**
- Fixture manifest records `fixture_id`, `source_url`, `retrieved_at`, `sha256`, `document_type`, `authority`, `entity`, `period`, `licence_note` and `relative_path`.
- `load_fixture_manifest() -> tuple[OfficialFixture, ...]` validates local files against SHA-256 before parser tests run.
- `parsers/contracts.py` owns `OfficialFixture`, `RawDocument`, `ParseWarning` and generic `ParseResult[T]` from the shared catalogue.

- [ ] **Step 1: Add failing fixture and dependency tests**

```python
def test_official_fixture_manifest_files_match_recorded_sha256():
    fixtures = load_fixture_manifest()
    assert {item.document_type for item in fixtures} >= {
        "sec_companyfacts", "esef_report_package", "priips_kid", "index_methodology"
    }
    for item in fixtures:
        assert sha256_file(item.path) == item.sha256
```

- [ ] **Step 2: Install dependencies in an isolated verification pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-parsers.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -c "import arelle, pdfplumber, defusedxml, feedparser, hypothesis; print('dependency_import_ok')"
.\.venv\Scripts\ruff.exe check src tests scripts
```

Expected: imports print `dependency_import_ok`; Ruff initially reports only actionable existing/new findings, which must be recorded before scope-limited fixes.

- [ ] **Step 3: Download and checksum exact official fixture classes**

Acquire:

- Microsoft SEC submissions and company facts from `https://data.sec.gov/submissions/CIK0000789019.json` and `https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json`, using a descriptive SEC-compliant User-Agent.
- One ESEF report package selected through `https://filings.xbrl.org/api/filings?filter[country]=NL&sort=-processed&page[size]=10`; retain the API response and package URL in the manifest and require filing system `ESEF`.
- Vanguard PRIIPs KID `https://fund-docs.vanguard.com/ie000q4j3cw6_priipskid_chen.pdf`.
- FTSE Global Equity Index Series Ground Rules linked from `https://www.lseg.com/en/ftse-russell/indices/geisac`.

Store immutable files under `tests/fixtures/official/<document_type>/`; never edit downloaded bytes. Add deliberately malformed derivatives only under `tests/fixtures/malformed/` and label them synthetic.

- [ ] **Step 4: Verify fixture and dependency evidence**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_official_fixture_manifest.py -q`  
Expected: all checksums, source URLs, authority labels and required document types pass.

- [ ] **Step 5: Checkpoint dependency changes**

Record package versions, licences, fixture URLs/checksums, download failures/retries and package-size impact in `RUN_STATE.json`, `REPORT.md` and `.ai_worklog/DECISIONS.md`.

---

### Task 3: Atomic I/O, Backups and Versioned Migrations

**Issues:** `ISSUE-0036`, `ISSUE-0040`, `ISSUE-0044`, `ISSUE-0039` foundations.

**Files:**
- Create: `src/etf_cockpit/core/atomic_io.py`, `src/etf_cockpit/core/migrations.py`
- Create: `tests/test_atomic_io.py`, `tests/test_schema_migrations.py`
- Modify: `src/etf_cockpit/data/import_pipeline.py`, `src/etf_cockpit/data/trust_artifacts.py`

**Interfaces:**
- `atomic_write_bytes(destination: Path, payload: bytes, validator: Callable[[Path], None]) -> AtomicWriteResult`.
- `backup_paths(paths: Iterable[Path], backup_root: Path) -> BackupManifest`.
- `Migration(version: int, name: str, apply: Callable[[MigrationContext], None])` and `run_migrations(context) -> MigrationReport`.

- [ ] **Step 1: Write failure-injection tests**

```python
def test_failed_validator_preserves_previous_destination(tmp_path):
    destination = tmp_path / "store.json"
    destination.write_text('{"valid": true}', encoding="utf-8")
    with pytest.raises(StoreValidationError):
        atomic_write_bytes(destination, b"broken", validator=lambda _: (_ for _ in ()).throw(StoreValidationError()))
    assert destination.read_text(encoding="utf-8") == '{"valid": true}'

def test_migration_is_idempotent_and_backup_manifest_matches_checksums(tmp_path):
    first = run_migrations(migration_context(tmp_path))
    second = run_migrations(migration_context(tmp_path))
    assert first.applied_versions
    assert second.applied_versions == ()
    assert verify_backup_manifest(first.backup_manifest)
```

- [ ] **Step 2: Verify RED, then implement atomic replacement**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_atomic_io.py tests\test_schema_migrations.py -q`  
Expected before implementation: missing module failures. Implement writes as sibling temporary files, flush/close, validate, then `Path.replace()`.

- [ ] **Step 3: Define migration versions**

Use versions:

```python
MIGRATIONS = (
    Migration(1, "provider_identity_evidence_v1", migrate_provider_identity),
    Migration(2, "official_documents_v1", migrate_official_documents),
    Migration(3, "universe_watchlists_v1", migrate_universe),
    Migration(4, "history_changes_v1", migrate_history),
)
```

Each migration accepts absent/empty stores, preserves recognised existing columns and writes schema metadata without inventing values.

- [ ] **Step 4: Route existing imports through atomic I/O**

Update `commit_price_import()` and trust-artifact dual writes to use atomic validation. Add permission-error and locked-file tests; assert previous clean stores survive.

- [ ] **Step 5: Run and checkpoint migration tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_atomic_io.py tests\test_schema_migrations.py tests\test_release_hardening.py -q
.\.venv\Scripts\python.exe -m compileall -q src tests
```

Expected: all pass. Record backup paths and migration versions before Task 4.

---

### Task 4: Finish-Check and Evidence Harness

**Issues:** `UPDATEV2-0029`, `ISSUE-0013`.

**Files:**
- Create: `scripts/dev_finish_check.py`, `tests/test_finish_check.py`
- Modify: `scripts/smoke_app.py`, `scripts/build_windows.bat`, `README.md`

**Interfaces:**
- `select_gates(changed_paths: Collection[Path], issue_ids: Collection[str]) -> FinishGatePlan`.
- `run_finish_gates(plan: FinishGatePlan, evidence_dir: Path) -> FinishGateReport`.
- CLI supports `--issues`, `--changed-paths-file`, `--no-build` only when no runtime/package path changed, and `--json-report`.

- [ ] **Step 1: Write gate-selection and false-closure tests**

```python
def test_parser_change_requires_parser_export_build_and_browser_gates():
    plan = select_gates({Path("src/etf_cockpit/parsers/esef_ixbrl.py")}, {"UPDATEV2-0013"})
    assert {"focused", "full", "fixtures", "export", "build", "browser", "computer_use"} <= set(plan.gates)

def test_runtime_change_cannot_use_no_build():
    with pytest.raises(FinishGateError):
        build_cli_plan(changed=["src/etf_cockpit/app/state.py"], no_build=True)
```

- [ ] **Step 2: Implement deterministic gate mapping**

Map paths to test files and closure gates in code, not shell string concatenation. Execute commands through argument arrays. Redact environment and store stdout/stderr/exit code in JSON without secrets.

- [ ] **Step 3: Extend smoke modes**

Add `source`, `native`, `portable-native`, `launcher`, `first-run` and `offline` modes. Require HTTP readiness, expected title, process path and controlled cleanup. Group text may use source-level payload checks when Flet semantics are absent, but UI closure still requires browser/computer-use evidence.

- [ ] **Step 4: Run focused harness tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_finish_check.py tests\test_launcher_workflow.py tests\test_flet_startup.py -q`  
Expected: all pass and no orphan process remains.

- [ ] **Step 5: Write Wave 2 release checkpoint**

Write exact changed paths to `evidence/wave2/changed-paths.txt`, then run `scripts/dev_finish_check.py --issues UPDATEV2-0029 ISSUE-0013 --changed-paths-file evidence/wave2/changed-paths.txt --json-report evidence/wave2/finish-report.json`. Keep both issues open until Task 23 but mark implementation gates ready.

---

### Task 5: End-to-End Browser, Chrome and Computer-Use Matrix

**Issues:** `ISSUE-0014`, `ISSUE-0045`.

**Files:**
- Create: `tests/test_e2e_workflow.py`, `tests/test_accessibility_contracts.py`
- Create: `configs/ui_acceptance.yaml`
- Modify: `src/etf_cockpit/app/router.py`, all current page/action components, `scripts/smoke_app.py`

**Interfaces:**
- `ui_acceptance.yaml` records route, control label, semantic key, action, expected status and screenshot name.
- Every interactive Flet control receives a stable `key` and tooltip/semantic label where Flet supports it.

- [ ] **Step 1: Inventory every route and button in a failing contract test**

```python
def test_every_declared_ui_action_has_unique_key_callback_and_expected_result():
    contracts = load_ui_acceptance_contracts()
    assert len({item.key for item in contracts}) == len(contracts)
    for item in contracts:
        assert item.callback
        assert item.success_signal or item.controlled_error_signal
```

- [ ] **Step 2: Add keys and central acceptance metadata**

Keys use `route.action`, for example `dashboard.refresh-yfinance`, `dashboard.run-algorithms`, `audit.export`, `filings.import-sec`, `universe.save` and `scores.expand.<instrument_id>`. Do not encode secrets or display values in keys.

- [ ] **Step 3: Implement source E2E test with injected providers**

Test refresh success/failure, algorithms, optional model unavailable state, score write, navigation and audit export using deterministic fixture providers. Assert visible workflow state and `session.jsonl` events.

- [ ] **Step 4: Run user-perspective matrix**

For source and packaged builds, use Playwright/in-app browser first, Chrome where available and Windows computer use for launcher/browser/file-picker interactions. Capture desktop 1440x900, narrow 900x900 and mobile 390x844 screenshots. Check nonblank pixels, title, route rendering, button clickability, row expansion, no overlap and console/session errors.

- [ ] **Step 5: Store evidence and checkpoint**

Write screenshots under `evidence/wave2/browser/`, computer-use observations to `evidence/wave2/computer-use.json` and update the closure matrix evidence paths for `ISSUE-0014` and `ISSUE-0045` without closing them yet.

---

### Task 6: Structured Workflow Runtime and Session Trace

**Issues:** `ISSUE-0069`, `UPDATEV2-0027`, `ISSUE-0012`.

**Files:**
- Create: `src/etf_cockpit/core/workflow.py`, `tests/test_workflow_runtime.py`
- Modify: `src/etf_cockpit/core/session_log.py`, `src/etf_cockpit/app/state.py`, `src/etf_cockpit/app/pages/dashboard.py`, `src/etf_cockpit/app/router.py`

**Interfaces:**

```python
class WorkflowStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    MANUAL_REVIEW = "manual_review"
    FAILED = "failed"

@dataclass(frozen=True)
class WorkflowStep:
    key: str
    label: str
    completed_units: int
    total_units: int | None

@dataclass(frozen=True)
class WorkflowResult:
    action_id: str
    workflow: str
    status: WorkflowStatus
    started_at: str
    finished_at: str
    message: str
    output_paths: tuple[str, ...]
    error_fingerprint: str | None
    retryable: bool
```

- [x] **Step 1: Write state-transition, redaction and logging-failure tests**

Test valid transitions, reject success after failure, log start before backend invocation, swallow a simulated log write error, redact tokens and preserve traceback fingerprint without raw secrets.

- [x] **Step 2: Implement `WorkflowController`**

Provide `start(workflow: str, label: str) -> str`, `step(action_id: str, step: WorkflowStep) -> None`, `finish(action_id: str, status: WorkflowStatus, message: str, output_paths: Iterable[Path]) -> WorkflowResult` and `fail(action_id: str, exc: Exception, retryable: bool) -> WorkflowResult`. Persist append-only activity entries and session events using the same action ID. Keep `ActivityEntry` compatibility conversion until all pages migrate.

- [x] **Step 3: Migrate current dashboard workflows**

Refresh yfinance, Run algorithms, Run forecasting models, Show scores, Renew data and Export audit packet must use `WorkflowController`. Disable duplicate clicks while an action is running and render step label, elapsed time and determinate progress when total units are known.

- [x] **Step 4: Verify runtime and browser behaviour**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_workflow_runtime.py tests\test_flet_startup.py tests\test_trust_critical_artifacts.py -q
.\.venv\Scripts\python.exe scripts\smoke_app.py --mode source --port 8570
```

Use browser/computer use to click each dashboard workflow once against deterministic providers and capture running plus final states.

- [x] **Step 5: Checkpoint Wave 3 progress**

Task 6 checkpoint (2026-07-12): the typed workflow/session runtime and
dashboard action paths were already present and were independently revalidated;
the task added the missing keyboard-operable `OutlinedButton` contract for all
four primary dashboard workflows. RED/GREEN evidence, focused 29-test
post-merge verification, compileall/Ruff, native package rebuild and direct
HTTP readiness, plus rendered source screenshots are recorded in
`.ai_worklog/task6-report.md` and `evidence/task6-dashboard-source*.png`.
The standard `smoke_app.py` source/native/portable fixture check remains
explicitly unavailable in the isolated worktree because the generated
Sparebanken/AURG trade-candidate fixture is absent; this is not attributed to
the dashboard change and no issue is closed by Task 6. PR 176 merged at
`16205d259380421d7041ffb46d61acce84ec1993`.

Record action IDs, screenshots, session-log assertions and any timing regression in `evidence/wave3/workflows/` and `RUN_STATE.json`.

---

### Task 7: Button Audit, Error/Recovery Centre and Performance Evidence

**Issues:** `ISSUE-0011`, `ISSUE-0040`, `ISSUE-0039`.

**Files:**
- Create: `src/etf_cockpit/app/pages/errors_recovery.py`
- Create: `src/etf_cockpit/core/errors.py`, `src/etf_cockpit/core/timing.py`
- Create: `tests/test_button_contracts.py`, `tests/test_error_recovery.py`, `tests/test_performance_contracts.py`
- Modify: `src/etf_cockpit/app/router.py`, `src/etf_cockpit/app/pages/diagnostics.py`, `configs/ui_acceptance.yaml`

**Interfaces:**
- `ErrorRecord(error_id, action_id, category, user_message, fingerprint, retryable, created_at)`.
- `ErrorStore.append()`, `recent(limit)`, `retry_request(error_id)`.
- `timed_step(action_id, step_name)` emits duration to session log and timing store.

- [x] **Step 1: Generate and validate the full button inventory**

Inventory every `on_click`, file picker, navigation control and expandable row. The test fails if a control lacks key, callback, expected result/error signal or acceptance test reference.

- [x] **Step 2: Implement controlled error classification**

Classify network timeout/rate limit as retryable; authentication, entitlement, invalid input, identity conflict and parser/schema failures as non-retryable until input/config changes. Store redacted messages and expose stack traces only when `ETF_COCKPIT_DEVELOPER_MODE=1`.

- [x] **Step 3: Add recovery UI and timing/cache diagnostics**

The route `/errors` shows last errors, action ID, readable message, timestamp and enabled Retry only when retryable. Diagnostics shows startup and workflow-step timings, cache hit/miss/invalidation and slow-step warnings. Heavy model/parser imports remain inside their workflow methods.

- [x] **Step 4: Run failure injection and performance tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_button_contracts.py tests\test_error_recovery.py tests\test_performance_contracts.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py tests\test_release_hardening.py -q
```

Inject timeout, permission, locked-file, malformed response and cache corruption failures; assert previous clean state survives and UI shows recovery guidance.

- [x] **Step 5: Wave 3 package and review gate**

Task 7 checkpoint (2026-07-12): all five steps passed on the isolated
`wave3/task7-error-recovery` branch and were integrated through PR 177
(`https://github.com/Thor2709/etf_ai_cockpit/pull/177`) at merge commit
`f6e0c9ca2105af2e4f176d4c0253339161fbe235`. The source-linked AST inventory
validator and negative omission regression cover all 25 routes and 63
contract records. Controlled error/recovery, atomic output preservation,
timing/cache diagnostics and lazy imports are covered by the focused tests.
Post-merge focused and affected suites, compileall, scoped Ruff and source
smoke passed. Windows build exited 0; native, portable-native and launcher
smoke passed against the verified data root; rendered Errors & Recovery and
Diagnostics browser evidence is checksum-recorded in
`.ai_worklog/task7-report.md`. Fresh independent re-review passed both
specification compliance and code quality with no Critical or Important
findings. The full isolated pytest run retains the documented generated-data /
trust-fixture and order-dependent transaction baseline failures; no Task 7
failure was attributed. `ISSUE-0011`, `ISSUE-0040` and `ISSUE-0039` remain open
because their complete closure dossiers and later programme gates are not yet
complete. Wave 3 Task 8 is next.

---

### Task 8: Canonical Data Contracts and Provider Registry

**Issues:** `UPDATEV2-0010`.

**Files:**
- Create: `src/etf_cockpit/data/contracts.py`, `src/etf_cockpit/data/provider_registry.py`
- Create: `tests/test_provider_registry.py`, `tests/test_data_contracts.py`
- Modify: `configs/data_providers.yaml`, `src/etf_cockpit/data/providers.py`, `src/etf_cockpit/app/pages/trust_evidence.py`

**Interfaces:**

```python
class SourceAuthority(StrEnum):
    OFFICIAL = "official"
    ISSUER = "issuer"
    VENDOR = "vendor"
    COMMUNITY = "community"
    MODEL = "model"

@dataclass(frozen=True)
class ProviderCapability:
    provider_id: str
    dataset_type: str
    status: str
    authority: SourceAuthority
    configured: bool
    entitlement: str
    rate_limit_note: str
    last_success_at: str | None
    error_fingerprint: str | None
```

- [x] **Step 1: Write provider capability and secret-redaction tests**

Assert disabled providers never probe, missing keys produce unavailable rather than exception, only `ok` capabilities can feed scoring, official authority outranks vendor, and serialised/redacted objects contain no key value.

- [x] **Step 2: Implement registry and provider adapters**

Registry keys: `yfinance`, `sec_edgar`, `filings_xbrl_org`, `fred`, `stooq`, `rss`, `manual_local`, `issuer_document`, `index_provider`. Every adapter implements `probe_capabilities() -> tuple[ProviderCapability, ...]` and lazy data methods.

- [x] **Step 3: Persist and render probes**

Write versioned `provider_probe_results.parquet` atomically. Provider Status displays enabled/configured/status, redacted configuration, authority, capabilities, entitlement/rate note and last success.

- [x] **Step 4: Run provider matrix**

Run live-safe no-key probes plus injected `ok`, timeout, 429, malformed and disabled tests. Inspect logs/exports for secrets with regexes covering `api_key`, `token`, `password`, bearer headers and `.env` values.

- [x] **Step 5: Checkpoint provider evidence**

Store provider matrix in `evidence/wave4/providers.json`, browser screenshot and redaction scan results.

**Task 8 checkpoint - 2026-07-12:** The canonical provider contracts, nine-provider
registry, disabled/no-key/timeout/rate/malformed/forbidden states, redaction
rules, atomic canonical-plus-legacy probe artefact and Provider Status route are
implemented on `wave3/task8-provider-registry`. Focused tests passed 14;
affected provider/trust/execution tests passed 42 with the documented unrelated
16-versus-45 identity fixture failure; compileall, scoped Ruff and source
smoke passed. PR 178 merged to `main` at `4c4eb00175237ad49b113adad8be3f8dcbfed618`.
The Windows build exited 0 and produced a portable bundle; native executable
smoke is not_applicable because PyInstaller was unavailable. Portable source
launcher HTTP readiness passed, and rendered `/providers` evidence is recorded
in `evidence/task8-provider-status.png` and
`evidence/task8-provider-status-mobile.png` with checksums in
`.ai_worklog/task8-report.md`. `UPDATEV2-0010` remains open/partial because its
complete audit-manifest, closure-matrix and independent issue-closure gates are
not yet satisfied. Wave 4 Task 9 is next.

---

### Task 9: Instrument Identity, Source Conflicts and Evidence Ledger

**Issues:** `UPDATEV2-0011`, `UPDATEV2-0021`, `UPDATEV2-0022` (the latter remains the already-closed local dossier and was not reopened).

**Files:**
- Create: `src/etf_cockpit/data/instrument_identity.py`, `source_conflicts.py`, `evidence_ledger.py`
- Create: `tests/test_instrument_identity.py`, `tests/test_source_conflicts.py`, `tests/test_evidence_ledger.py`
- Modify: `src/etf_cockpit/data/trust_artifacts.py`, `src/etf_cockpit/signals/simple_scores.py`, `src/etf_cockpit/app/pages/trust_evidence.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class CanonicalIdentity:
    instrument_id: str
    isin: str | None
    isin_status: str
    ticker: str
    exchange: str | None
    mic: str | None
    currency: str | None
    asset_type: str
    share_class: str | None
    provider_symbols: Mapping[str, str]
    confidence: str
    warnings: tuple[str, ...]

resolve_identity: Callable[[Iterable[IdentityClaim]], IdentityResolution]
resolve_conflicts: Callable[[Iterable[MetricClaim]], ConflictResolution]
ledger_entry_for_component: Callable[[SimpleScoreComponent, EvidenceSource], EvidenceLedgerEntry]
```

- [x] **Step 1: Write mismatch and authority tests**

Cover ticker/ISIN mismatch, exchange/currency variants, ETF share-class separation, unknown ISIN, official-vendor material conflict and missing source ID. Missing source must make a component score-ineligible.

- [x] **Step 2: Extract existing trust-artifact logic**

Move generation into typed modules while retaining wrappers named `write_instrument_identity`, `write_source_conflicts`, `write_evidence_ledger` and `write_score_components` so current callers remain stable.

- [x] **Step 3: Enforce provenance in scoring**

Every component records `source_id`, authority, as-of date, freshness and conflict ID. Conflicted material official/vendor values lower evidence quality or produce manual review; no claim is silently overwritten.

- [x] **Step 4: Add UI conflict and provenance detail**

Evidence Ledger, Filings, ETF Disclosures and Instrument Detail display canonical selection, rejected claims and human-readable conflict reason.

- [ ] **Step 5: Run focused and regression tests and complete the Wave 4 closure gate**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_instrument_identity.py tests\test_source_conflicts.py tests\test_evidence_ledger.py tests\test_simple_scores.py tests\test_trust_critical_artifacts.py -q`.

---

**Task 9 integration checkpoint - 2026-07-12:** The implementation and fix
passes were independently re-reviewed at `262946e` with specification,
code-quality and READY_FOR_INTEGRATION approval and no Critical, Important or
Minor findings. PR 179 (`https://github.com/Thor2709/etf_ai_cockpit/pull/179`)
merged into `main` at `ec5d166ee32235367f58d31f3835854a14e11ba8`. The focused
Task 9 slice passed 13 tests, the candidate compatibility regressions passed
3 tests, and the affected persistence/evidence/scope bundle passed 35 tests;
bytecode-disabled compilation, forced compileall, scoped Ruff, source smoke,
portable source-launcher readiness and rendered Provider Status evidence are
recorded in `.ai_worklog/task9-report.md`.
`UPDATEV2-0011` and `UPDATEV2-0021` remain open/partial because the complete
issue-level closure matrix, package, audit/export and final browser gates are
not yet satisfied. `UPDATEV2-0022` remains closed. The next dependency-valid
implementation task is Task 10, Data Health Centre.

### Task 10: Data Health Centre

**Issues:** `ISSUE-0035`.

**Files:**
- Create: `src/etf_cockpit/app/pages/data_health.py`, `src/etf_cockpit/data/health.py`, `tests/test_data_health.py`
- Modify: `src/etf_cockpit/app/router.py`, `src/etf_cockpit/app/pages/dashboard.py`

**Interfaces:**
- `build_data_health(config: AppConfig, project_root: Path) -> DataHealthReport`.
- Report contains prices, FX, holdings, fundamentals, news, macro, forecasts, backtests, provider probes, official documents and migration status with row count, checksum, as-of, freshness, last success, last failure and warnings.

- [x] **Step 1: Write health aggregation tests**

Test valid, missing, stale, corrupt and schema-mismatch stores. Corrupt/missing files return status rows and cannot crash the page.

- [x] **Step 2: Implement deterministic inventory**

Use schema registry and provenance metadata; do not infer freshness from filesystem time when an explicit as-of field exists.

- [x] **Step 3: Build Data Health UI**

Add `/data-health`, dashboard summary, filters by status/dataset/provider and links to related Provider, Filings, ETF and Error pages.

- [x] **Step 4: Browser and export verification**

Render mixed healthy/stale/missing fixtures in source and packaged UI, capture screenshots and export the health table to CSV with visible output path.

- [x] **Step 5: Wave 4 gate and integration**

Run focused plus full tests, package build, Provider/Evidence/Data Health browser matrix, secret scan and audit-export interim check. Mark five Wave 4 dossiers ready only after independent review.

Task 10 implementation is independently approved and its focused, affected,
compile, lint, source-smoke, export, portable-build, native/portable-smoke,
direct packaged-readiness, semantic focus and source/package browser evidence
is recorded in `.ai_worklog/task-10-report.md` and `evidence/final/`. The
authoritative full suite passes after the atomic staging and provenance fixes.
PR 180 merged the reviewed branch into `main` at
`3eab7a414a54c74553b09ebc4085902af0ffc33e`; post-merge focused/full/smoke
verification passed and `ISSUE-0035` moved to the canonical closed ledger.
GitHub Issue synchronisation is complete. Task 11 is implementation-complete
and merged; its four issues remain open for their required final release,
package, browser and clean-first-run closure evidence.

---

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

- [x] **Step 1: Write CRUD, duplicate and guardrail tests**

Cover add/edit/disable/remove; duplicate ID/ISIN/ticker across tiers; explicit `needs_verification`; no workflow auto-run after save; daily ETF/stock support; intraday/futures/options/crypto unsupported; leveraged/inverse high-risk.

- [x] **Step 2: Implement migrated universe persistence**

Import current primary YAML and candidate CSV into one versioned store while retaining export back to existing formats for compatibility. Preserve all 15 Sparebanken rows and unknown ISIN states.

- [x] **Step 3: Build Universe/Watchlist UI**

Use Primary, Secondary and Sparebanken tabs, search/filter, validated edit dialog and status column. Save only after validation; show pending-refresh without triggering refresh.

- [x] **Step 4: Build first-run wizard**

Collect base currency, region, asset scope, risk profile, horizon and initial tickers; validate locally/yfinance when online; explain local-only evidence and non-advice; support offline completion with unresolved tickers disabled.

- [ ] **Step 5: Test clean first run and package**

Run with temporary empty root, complete wizard using computer use, restart, verify persisted universe, then run source/full tests and Wave 5 package/browser gate.

Task 11 Steps 1-4 are complete and independently reviewed. The focused
post-merge bundle passed 57 tests; compileall, scoped Ruff, the governance
static boundary and source smoke passed. Step 5 remains open because the
issue-specific clean-first-run, package and browser evidence has not yet been
freshly captured. PR 181 merged the implementation into `main` at
`2eae5dea8dd1d789dd000383901e591ee4645d83`; the next dependency-valid
implementation is Task 12, SEC EDGAR Provider and Official Statement Facts.

---

### Task 12: SEC EDGAR Provider and Official Statement Facts

**Issues:** `UPDATEV2-0012`.

**Files:**
- Create: `src/etf_cockpit/data/sec_edgar_provider.py`, `src/etf_cockpit/parsers/sec_facts.py`
- Create: `tests/test_sec_edgar_provider.py`, `tests/test_sec_facts_parser.py`
- Modify: `src/etf_cockpit/app/pages/trust_evidence.py`, `src/etf_cockpit/app/state.py`, `src/etf_cockpit/core/paths.py`

**Interfaces:**
- `SecEdgarProvider.fetch_submissions(cik) -> RawDocument` and `fetch_companyfacts(cik) -> RawDocument` with SEC-compliant User-Agent and bounded rate.
- `parse_companyfacts(path: Path, identity: CanonicalIdentity) -> ParseResult[StatementFact]`.
- Statement facts retain taxonomy, concept, unit, value, start/end/instant, filed date, form, accession, fiscal year/period and source ID.

- [x] **Step 1: Write real-fixture parser tests**

Assert Microsoft fixture identity, at least one recognised official fact, exact accession/form/unit retention and no invented value. Add malformed JSON, wrong CIK and ambiguous-unit tests.

- [x] **Step 2: Implement immutable fetch and parser**

Use conditional requests where supported, checksum raw JSON and refuse identity mismatch. Parser maps a small explicit canonical concept table while retaining all original concepts separately.

- [x] **Step 3: Commit clean facts atomically**

Write `data/clean/statement_facts.parquet` and filing inventory with schema version and source IDs. Official SEC facts outrank vendor claims only for matching entity, concept, unit and period.

- [x] **Step 4: Add Filings UI workflow**

Add CIK-resolved import button, progress, filings/facts table, source URL and mapping warnings. Missing network must show controlled unavailable while local fixture import remains functional.

- [ ] **Step 5: Verify parser, export and packaged UI**

**Task 12 implementation checkpoint (2026-07-13):** Steps 1-4 are implemented,
independently reviewed and merged through PR 182 at `dc9765ff97f14cc29e9dd7a4f02d669ce0e5ee7f`.
Focused SEC/trust/UI/accessibility verification passed 54 tests; scoped Ruff,
compileall and diff checks passed. The issue remains open with implementation
complete but closure pending fresh package/browser, clean-first-run and
configured live SEC-network evidence. `execution_allowed=false` is unchanged.

Run focused tests, import real fixture through UI, export audit ZIP and verify SEC raw checksum/fact mappings. Rebuild and capture packaged Filings page plus computer-use import interaction.

---

### Task 13: ESEF/iXBRL Provider and IFRS Mapping

**Issues:** `UPDATEV2-0013`.

**Files:**
- Create: `src/etf_cockpit/data/esef_provider.py`, `src/etf_cockpit/parsers/esef_ixbrl.py`
- Create: `tests/test_esef_provider.py`, `tests/test_esef_ixbrl_parser.py`
- Modify: `src/etf_cockpit/app/pages/trust_evidence.py`, `src/etf_cockpit/app/state.py`

**Interfaces:**
- `FilingsXbrlOrgProvider.list_filings(country, limit) -> ProviderResult` and `download_report_package(filing_id) -> RawDocument`.
- `parse_esef_package(path: Path) -> ParseResult[StatementFact]` invokes Arelle through a bounded adapter and captures validation messages.
- `map_ifrs_fact(fact: XbrlFact) -> CanonicalMapping` returns mapped only for explicit configured IFRS concepts; extensions remain unmapped with warnings.

- [x] **Step 1: Write official report-package tests**

Assert valid package checksum, LEI/entity, reporting period, extracted facts, decimals/unit/context and extension retention. Test ZIP traversal rejection, malformed archive, unsupported report package and Arelle validation failure.

- [x] **Step 2: Implement safe package validation**

Reject absolute paths, backslashes, `..`, oversized uncompressed totals and unsupported extensions before extraction. Parse from a task-local temporary directory; preserve original package unchanged.

- [x] **Step 3: Implement Arelle adapter and IFRS mapping**

Lazy-import Arelle, enforce timeout in a child process, collect facts/messages into serialisable records and map only configured IFRS concepts. No extension heuristic may silently become canonical.

- [x] **Step 4: Add local import and API discovery UI**

Filings page supports local package picker and public API discovery/download. Show validation severity, extensions, mapping confidence and source authority.

- [ ] **Step 5: Verify all strict gates**

Run parser/property/fuzz tests, UI import, clean store, conflict resolution, audit export, source and packaged browser/computer-use checks. Keep issue open if Arelle cannot parse the official fixture.

**Task 13 implementation checkpoint - 2026-07-13:** Steps 1-4 are implemented and
independently approved on branch `wave4/task13-esef`, commit `44db2c2`, merged
through PR 183 at `231f5be1055121e878d614b353a919d0d61d102e`. The focused
provider/parser/statement bundle and worker-level Arelle serialisation tests
pass; scoped Ruff, compileall and diff checks pass. `UPDATEV2-0013` remains
open as implementation-complete/closure-pending for the strict package,
audit/export, clean-first-run and browser/computer-use gates.

---

### Task 14: ETF Document Registry and Holdings Normaliser

**Issues:** `UPDATEV2-0015`, `UPDATEV2-0016`.

**Files:**
- Create: `src/etf_cockpit/data/fund_documents.py`, `src/etf_cockpit/data/fund_holdings.py`
- Create: `tests/test_fund_documents.py`, `tests/test_fund_holdings.py`
- Modify: `src/etf_cockpit/app/pages/trust_evidence.py`, `src/etf_cockpit/app/pages/risk.py`, `src/etf_cockpit/data/trust_artifacts.py`

**Interfaces:**
- `register_document(path, document_type, instrument_id, source_url, authority) -> FundDocument`.
- `normalise_holdings(frame, instrument_id, as_of, source) -> HoldingsNormalisationResult`.
- Completeness states: `full`, `partial`, `invalid`, `stale`, `unavailable`.

- [x] **Step 1: Write document and holdings tests**

Cover checksum/date/type inventory, missing document rows, exact duplicate handling, 99-101% full holdings tolerance, partial top holdings, invalid negative/overweight values, stale evidence-quality cap and Risk-page aggregation.

- [x] **Step 2: Implement registry and atomic stores**

Write versioned `fund_documents.parquet` and holdings records with source IDs. Every configured ETF receives inventory rows for factsheet, KID, prospectus/report, holdings and methodology even when missing.

- [x] **Step 3: Integrate evidence eligibility**

Full/current issuer holdings receive issuer authority; yfinance top holdings remain partial vendor evidence; stale/invalid holdings cannot support current exposure scoring.

- [x] **Step 4: Build ETF Disclosures and Risk panels**

Show document type/date/checksum/source, holdings completeness/freshness/confidence, missing requirements and exposure contribution.

- [ ] **Step 5: Verify import/export/package**

Use real issuer holdings where publicly available or a real downloaded issuer CSV; if unavailable for the selected ETF, use the existing imported issuer file as UI proof but do not claim live coverage. Verify audit inventory and packaged panels.

**Task 14 implementation checkpoint - 2026-07-13:** Steps 1-4 are implemented
and independently approved on branch `wave4/task14-fund-docs`, head commit
`a7cb185`, merged through PR 184 at merge commit
`49abaf4907f81ab2798a394d11cf2ddaf5d3b031`. The registry and holdings stores
preserve checksums, source IDs, explicit missing rows, authority and eligibility
boundaries; local document and CSV/XLSX holdings imports use fail-closed
validation and atomic four-file publication; ETF Disclosures, Risk and
Instrument Detail surfaces are wired and the two new UI controls are
acceptance-covered. Focused Task 14/Risk/Instrument Detail/trust
registration/button tests passed, scoped Ruff, compileall and diff checks
passed, and the fresh independent reviewer returned SPEC PASS, CODE PASS and
READY with no findings. `UPDATEV2-0015` and `UPDATEV2-0016` remain open as
implementation-complete/closure-pending for strict audit/export, package,
clean-first-run and browser/computer-use evidence; Step 5 is not yet passed.

---

### Task 15: PRIIPs KID and Index Methodology Parsers

**Issues:** `UPDATEV2-0017`, `UPDATEV2-0019`.

**Files:**
- Create: `src/etf_cockpit/parsers/priips_kid.py`, `index_methodology.py`
- Create: `tests/test_priips_kid_parser.py`, `tests/test_index_methodology_parser.py`
- Modify: `src/etf_cockpit/app/pages/trust_evidence.py`, `src/etf_cockpit/signals/simple_scores.py`

**Interfaces:**
- `parse_priips_kid(path: Path, expected_isin: str | None) -> ParseResult[PriipsKidRecord]`.
- KID fields: product, ISIN, manufacturer, SRI, cost fields, holding period, scenarios, document date, extraction confidence and warnings.
- `parse_index_methodology(path: Path, provider: str) -> ParseResult[IndexMethodologyRecord]`.
- Methodology fields: provider, index/series, version/date, eligibility, weighting, review/rebalance frequency, caps, source pages and confidence.

- [ ] **Step 1: Write official PDF golden tests**

Use the checksummed Vanguard KID and FTSE GEIS rules. Assert exact known document identity/date plus bounded recognised fields. Test image-only/empty PDF, wrong ISIN, missing SRI, malformed cost table and unsupported language warning.

- [ ] **Step 2: Implement deterministic PDF extraction**

Use `pdfplumber` page text with normalised whitespace and page references. Extract with labelled regex/table rules; never infer missing numbers. Return warnings and confidence per field.

- [ ] **Step 3: Integrate registry, scoring and conflicts**

KID costs/risk may support cost/risk evidence with issuer authority but cannot substitute for holdings/prospectus. Missing KID/methodology caps relevant ETF evidence quality and creates manual-review warning. Holdings/methodology conflicts remain visible.

- [ ] **Step 4: Add ETF Disclosure panels and import buttons**

Display fields, source pages, confidence, warnings, document checksum/version and explicit missing states. File picker imports must show progress and controlled parse errors.

- [ ] **Step 5: Strict closure verification**

Run official/malformed fixture tests, UI imports, audit ZIP extraction and packaged browser/computer-use import. Both issues remain open until screenshots show parsed records and audit checksums.

---

### Task 16: Fundamentals, News, Point-in-Time Validation and Free Providers

**Issues:** `ISSUE-0023`, `ISSUE-0025`, `ISSUE-0054`, `ISSUE-0055`.

**Files:**
- Create: `src/etf_cockpit/data/fundamentals.py`, `news_context.py`, `rss_provider.py`, `fred_provider.py`
- Create: `tests/test_fundamentals.py`, `tests/test_news_context.py`, `tests/test_optional_providers.py`
- Modify: `src/etf_cockpit/data/stooq_provider.py`, `src/etf_cockpit/data/yfinance_provider.py`, `src/etf_cockpit/app/pages/trust_evidence.py`, `src/etf_cockpit/app/pages/etf_detail.py`

**Interfaces:**
- `build_fundamental_evidence(claims, identity, as_of) -> FundamentalEvidence` with valuation, profitability, leverage, growth, shareholder return and eligibility.
- `validate_news_item(item, decision_time) -> NewsValidation` requires published/ingested/source/provider/mapping/available-at fields.
- Optional providers implement the Task 8 capability interface and remain disabled by default.

- [ ] **Step 1: Write missing-vs-bad and point-in-time tests**

Assert missing key fundamentals produce `not_score_eligible`, genuinely weak present metrics remain valid negative evidence, stale fields warn, sector comparison can be unavailable, and news after decision time or with ambiguous timestamp is rejected from backtests.

- [ ] **Step 2: Implement clean news and fundamentals stores**

Store raw items immutably and clean rows with authority, credibility, timestamp validation and `executable_authority=false`. SEC facts outrank vendor fundamentals; vendor fields show limitations.

- [ ] **Step 3: Implement optional provider states**

EDGAR public access can be enabled without key; FRED missing key, Stooq and RSS disabled/offline states are explicit. No optional provider becomes required for app startup or scoring.

- [ ] **Step 4: Build News/Filings dashboard and contradiction panel**

Show URL, published/ingested time, source/provider, credibility, mapping and contradictions against deterministic evidence. News cannot change final action.

- [ ] **Step 5: Wave 6 integration gate**

Run all parser/provider/property/fuzz tests, raw-clean-ledger-score-export integration, full suite, package rebuild and browser/computer-use workflows for Filings, ETF Disclosures, News and Instrument Detail. Request parser-focused and security-focused reviews before marking ten Wave 6 dossiers ready.

---

### Task 17: Score History, Run Comparison and Feature Drivers

**Issues:** `ISSUE-0067`, `ISSUE-0034`, `ISSUE-0047`.

**Files:**
- Create: `src/etf_cockpit/data/score_history.py`, `run_changes.py`, `src/etf_cockpit/signals/feature_drivers.py`
- Create: `tests/test_score_history.py`, `tests/test_run_changes.py`, `tests/test_feature_drivers.py`
- Modify: `src/etf_cockpit/data/trust_artifacts.py`, `src/etf_cockpit/app/components/simple_scores.py`
- Create: `src/etf_cockpit/app/pages/what_changed.py`

**Interfaces:**
- `append_score_run(scores, run_id, created_at) -> ScoreHistoryWriteResult` is idempotent by run ID and snapshot hash.
- `compare_runs(current_run_id, previous_run_id) -> RunChangeReport`.
- `build_feature_drivers(scores, ledger) -> pd.DataFrame` emits required driver schema.

- [ ] **Step 1: Write idempotency and no-authority tests**

Cover no history, one run, multiple runs, duplicate run replacement, malformed rows, score/component deltas and proof that historical trend/driver text cannot alter current action.

- [ ] **Step 2: Extract existing history/driver logic**

Preserve wrapper functions in `trust_artifacts.py`; migrate current Parquet data through Task 3 migration version 4.

- [ ] **Step 3: Implement complete run comparison**

Compare scores/ranks, warnings, freshness, model availability, forecasts, news inventory, backtest trust and portfolio risk. Generate structured changes plus plain-English summaries from deterministic templates.

- [ ] **Step 4: Add history and What Changed UI**

Expanded score rows show chart, latest/previous/delta and no-history guidance. `/what-changed` shows filters and dashboard digest without horizontal scrolling.

- [ ] **Step 5: Verify history UI/export**

Create two deterministic runs, verify deltas, screenshots and audit history/change entries in source and packaged UI.

---

### Task 18: Crowding, Sector/Theme Attribution and Friction-Adjusted Edge

**Issues:** `ISSUE-0052`, `ISSUE-0059`, `ISSUE-0064`.

**Files:**
- Create: `src/etf_cockpit/features/crowding.py`, `benchmark_attribution.py`
- Create: `src/etf_cockpit/signals/friction_edge.py`
- Create: `tests/test_crowding.py`, `tests/test_benchmark_attribution.py`, `tests/test_friction_edge.py`
- Modify: `src/etf_cockpit/features/regime.py`, `src/etf_cockpit/signals/simple_scores.py`, Scores/Risk/Instrument Detail components

**Interfaces:**
- `build_correlation_clusters(prices, metadata, window=120) -> ClusterReport`.
- `build_benchmark_attribution(instrument_returns, broad_returns, sector_returns) -> AttributionResult`.
- `estimate_friction_edge(evidence_score, volatility, costs, scenario) -> FrictionEdgeResult`.

- [ ] **Step 1: Write deterministic numerical and insufficient-data tests**

Test known correlation clusters, AI/semi/theme concentration, broad vs sector alpha proxy, missing sector benchmark `N/A`, gross/net bps, edge-to-cost ratio and low/base/high cost scenarios.

- [ ] **Step 2: Extract and strengthen existing calculations**

Move existing correlation/benchmark/friction logic into typed modules, preserve wrappers and add sample-size/as-of/source fields. Candidate rows without clean price panels remain unavailable.

- [ ] **Step 3: Add metadata-driven theme warnings**

Use configured sector/theme labels and cluster membership; do not infer themes from company names or model output.

- [ ] **Step 4: Add UI and export fields**

Scores, Risk and Instrument Detail show cluster, contribution, broad/sector attribution and gross/net edge/cost scenario with `N/A` where unsupported.

- [ ] **Step 5: Run analytics regression**

Run new tests plus `test_evidence_derivatives.py`, `test_simple_scores.py`, `test_risk_analytics.py`, `test_signal_gates.py` and audit export tests.

---

### Task 19: Comprehensive Instrument Detail

**Issues:** `ISSUE-0019`.

**Files:**
- Create: `src/etf_cockpit/app/pages/instrument_detail.py`, `src/etf_cockpit/app/selectors/instrument_detail.py`, `src/etf_cockpit/app/selectors/__init__.py`
- Create: `tests/test_instrument_detail.py`
- Modify: `src/etf_cockpit/app/pages/etf_detail.py`, `src/etf_cockpit/app/router.py`, score-row navigation

**Interfaces:**
- `build_instrument_detail(snapshot, instrument_id) -> InstrumentDetailViewModel` combines canonical stores only.
- View model has identity, price/freshness, three score dimensions, final label/reason/gates, technicals, liquidity, risk, attribution, fundamentals, ETF disclosures, news, forecasts, backtests, paper history, journal and run changes.

- [ ] **Step 1: Write ETF, stock, Sparebanken and missing-data view-model tests**

Assert all required sections, correct identity/group, unavailable states, source links and no crash when any optional store is empty/corrupt.

- [ ] **Step 2: Implement selectors without UI calculations**

Selectors join by canonical instrument ID and source IDs. UI modules format data but cannot recalculate scores or resolve conflicts.

- [ ] **Step 3: Build route and score-row navigation**

Use `/instrument/<id>` or selected-state equivalent supported by current Flet routing. Retain `/etf` compatibility redirect until tests prove no broken links.

- [ ] **Step 4: Build inspectable panels**

Use tabs or full-width sections, not nested cards. Include export controls and source/conflict badges. Maintain dense operational layout and stable responsive dimensions.

- [ ] **Step 5: Browser/computer-use detail matrix**

Navigate from representative ETF, stock and Sparebanken score rows; expand all sections; capture desktop/mobile screenshots and inspect browser/session logs.

---

### Task 20: Import/Export, Backup/Restore, Charts and Accessible Tables

**Issues:** `ISSUE-0036`, `ISSUE-0042`, `ISSUE-0044`, `ISSUE-0041`.

**Files:**
- Create: `src/etf_cockpit/app/pages/import_export.py`
- Create: `src/etf_cockpit/data/backup_restore.py`, `src/etf_cockpit/data/export_tables.py`
- Create: `tests/test_import_export.py`, `tests/test_backup_restore.py`, `tests/test_accessible_tables.py`
- Modify: `src/etf_cockpit/app/components/tables.py`, `charts.py`, `src/etf_cockpit/app/pages/settings.py`, `backtests.py`, `risk.py`

**Interfaces:**
- `validate_import(import_type, path) -> ImportPreview`; `commit_import(preview_id) -> ImportCommitResult`.
- `export_table(table_id, frame, destination) -> ExportResult`.
- `create_backup(paths, destination) -> BackupManifest`; `validate_restore(archive) -> RestorePreview`; `commit_restore(preview) -> RestoreResult`.

- [ ] **Step 1: Write preview-before-commit and round-trip tests**

Test broker/candidate/notes/holdings/news imports; reject invalid files before commit; export every major table; backup/restore checksums; wrong schema/zip traversal/corrupt archive; preserve current state on failure.

- [ ] **Step 2: Implement central operations service**

Reuse Task 3 atomic I/O and migrations. Backup includes data/configs/version/changelog and manifest, excludes secrets and transient build/log caches unless explicitly selected.

- [ ] **Step 3: Build Import/Export UI**

File picker -> validation preview -> explicit commit -> result path. Export controls show output path and controlled errors. Settings shows app version, last rebuild timestamp, data root and changelog.

- [ ] **Step 4: Improve tables/charts/accessibility**

Add search/sort where useful, explicit labels/tooltips, keyboard focus where Flet permits, non-colour status text, desktop/mobile constraints, price/history and backtest equity/drawdown charts, and CSV exports.

- [ ] **Step 5: Computer-use acceptance**

Use Windows computer use for file picker imports, export save paths, backup creation, restore preview/cancel/commit, keyboard navigation and responsive screenshots. Verify no overlap, clipping or unreadable controls.

---

### Task 21: Complete Audit Packet and Non-Executable External Audit Import

**Issues:** `UPDATEV2-0028`.

**Files:**
- Modify: `src/etf_cockpit/chatgpt_bridge/export_pack.py`, `import_audit.py`, `src/etf_cockpit/app/pages/chatgpt_audit.py`
- Create: `tests/test_complete_audit_packet.py`
- Create: `configs/audit_manifest.yaml`

**Interfaces:**
- Manifest declares required path, schema version, source authority, SHA-256 and unavailable policy for each artefact.
- `validate_audit_archive(path) -> AuditValidationReport` verifies required entries and checksums.

- [ ] **Step 1: Write failing complete-manifest test**

Require provider states, identities, statement facts/inventory, ETF documents/holdings/KID/methodology, news validation, conflicts, ledger/components, score/history/changes, drivers, clusters, attribution, edge/cost, health, workflow/session, configs, issue dossiers and checksum manifest.

- [ ] **Step 2: Extend export deterministically**

Include every available canonical artefact; when optional evidence is genuinely unavailable, include a schema-valid unavailable record with reason, not an omitted file or invented row.

- [ ] **Step 3: Harden redaction and external import**

Scan archive content for configured secrets and common key patterns. Imported external audit remains a note with `executable_authority=false` and cannot alter scores/actions/configuration.

- [ ] **Step 4: UI and extraction proof**

Export through source and packaged UI, show included artefacts/output path, extract to a temporary verification directory and validate every checksum.

- [ ] **Step 5: Wave 8 audit checkpoint**

Store archive, extracted manifest report, secret-scan result and browser/computer-use evidence under `evidence/wave8/audit/`.

---

### Task 22: Full Verification, Bug Hunt and Independent Review

**Issues:** All 41 final evidence gate.

**Files:**
- Modify only files required by verified defects.
- Create: `evidence/final/verification-manifest.json`, `evidence/final/browser/`, `evidence/final/computer-use.json`
- Update: all worklogs and `RUN_STATE.json`

**Interfaces:** Verification manifest records command, start/end, exit code, output digest, artefacts and linked issue criteria.

- [ ] **Step 1: Run static, schema, secret and dependency checks**

```powershell
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\mypy.exe src\etf_cockpit\core src\etf_cockpit\parsers src\etf_cockpit\data\contracts.py
.\.venv\Scripts\python.exe -m compileall -q scripts src tests
.\.venv\Scripts\python.exe -m pytest tests\test_official_fixture_manifest.py tests\test_data_contracts.py tests\test_schema_migrations.py -q
```

Run local secret scan over source, configs, logs, evidence, exports and portable package; compare against known `.env` values without printing them.

- [ ] **Step 2: Run focused, property/fuzz, integration and full tests**

Run every test module from Tasks 1-21, then `.\.venv\Scripts\python.exe -m pytest -q`. Any failure enters systematic debugging: reproduce alone, write/confirm regression, fix, rerun focused and affected gates.

- [ ] **Step 3: Run clean-first-run, migration and recovery drills**

Use temporary roots for no-data onboarding, current-data migration, interrupted migration, corrupt store, locked file, provider offline, parser malformed, backup/restore and cache invalidation. Verify the original workspace data checksum remains unchanged except for intentional migrated outputs.

- [ ] **Step 4: Rebuild and launch all modes**

```powershell
.\scripts\build_windows.bat
.\.venv\Scripts\python.exe scripts\smoke_app.py --mode source --port 8580
.\.venv\Scripts\python.exe scripts\smoke_app.py --mode native --port 8581
.\.venv\Scripts\python.exe scripts\smoke_app.py --mode portable-native --port 8582
cmd /c "set ETF_COCKPIT_PORT=8583&& Launch_Latest_ETF_AI_Cockpit.bat"
```

Repeat with preferred port busy/non-HTTP, existing ready server and locked native/portable outputs. Stop only repo-local verification processes and confirm test ports are released.

- [ ] **Step 5: Run complete browser/Chrome/computer-use matrix**

Verify all routes, every UI contract, official imports, progress/success/failure/retry, universe CRUD, first run, row detail, Data Health, What Changed, exports, backup/restore and audit. Capture desktop/narrow/mobile screenshots and browser console/session logs. Do not count loading frames as evidence.

- [ ] **Step 6: Request independent reviews**

Request bounded reviews for architecture/data integrity, parsers/fixtures, security/secrets, financial-safety gates, UI/accessibility and acceptance-criteria coverage. Verify every finding against code and add regression tests for valid defects.

- [ ] **Step 7: Rerun affected and full gates after review fixes**

No completion claim may use pre-fix output. Refresh `verification-manifest.json` with the final commands and evidence only.

---

### Task 23: Issue Dossiers, Tracker Closure and Final Handoff

**Issues:** All 41 closure decisions.

**Files:**
- Create: `evidence/final/issues/<issue-id>.json` and `.md` for each issue
- Modify: `issues/open.md`, `issues/closed.md`, `ISSUES.md`, `CLOSED.md`, `REPORT.md`, `plan.md`
- Modify: `RUN_LOG.md`, `HANDOFF.md`, `.ai_worklog/WORKLOG.md`, `CHANGES.md`, `TESTING.md`, `ERRORS_AND_FINDINGS.md`, `DECISIONS.md`

**Interfaces:** `scripts/closure_status.py --finalise` may move an issue only when `ClosureEvaluation.ready` is true and all evidence files/checksums exist.

- [ ] **Step 1: Generate 41 dossiers**

Each dossier lists every acceptance criterion, source file/interface, focused test, UI route/action, export artefact, build/browser/computer-use evidence, limitations and final state.

- [ ] **Step 2: Validate exact issue set and closure gates**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\closure_status.py --matrix configs\closure_matrix.yaml --evidence-root evidence\final --json-report evidence\final\closure-report.json
```

Expected target: 41 records, 41 `ready=true`, zero missing gates and zero unknown IDs. If any gate is missing, leave that issue open/blocked and continue implementation rather than editing around the evaluator.

- [ ] **Step 3: Update trackers atomically**

Move only ready issues to `issues/closed.md`; remove their canonical open sections or mark them superseded with a direct closure link according to existing tracker format. Root indexes must match canonical trackers.

- [ ] **Step 4: Run post-tracker finish check**

Run full tests, closure-matrix tests, report/tracker consistency, source smoke and final file/checksum checks. Documentation edits do not require another package build unless they are embedded in the package; if README/changelog is packaged, rebuild once and re-run packaged smoke.

- [ ] **Step 5: Final cleanup and handoff**

Confirm no verification process/listener remains, no temp fixture extraction is left under source/data, no secret appears in evidence and all user data backups are documented. `HANDOFF.md` must state no Git repo/commit, final package paths, exact commands/results and an exact resume prompt only if any issue remains non-closed.

## Issue Coverage Audit

Wave 2: `UPDATEV2-0029`, `ISSUE-0013`, `ISSUE-0014`, `ISSUE-0045`.  
Wave 3: `ISSUE-0069`, `UPDATEV2-0027`, `ISSUE-0011`, `ISSUE-0012`, `ISSUE-0040`, `ISSUE-0039`.  
Wave 4: `UPDATEV2-0010`, `UPDATEV2-0011`, `UPDATEV2-0021`, `UPDATEV2-0022`, `ISSUE-0035`.  
Wave 5: `ISSUE-0068`, `ISSUE-0018`, `ISSUE-0017`, `ISSUE-0056`.  
Wave 6: `UPDATEV2-0012`, `UPDATEV2-0013`, `UPDATEV2-0015`, `UPDATEV2-0016`, `UPDATEV2-0017`, `UPDATEV2-0019`, `ISSUE-0023`, `ISSUE-0025`, `ISSUE-0054`, `ISSUE-0055`.  
Wave 7: `ISSUE-0067`, `ISSUE-0047`, `ISSUE-0052`, `ISSUE-0059`, `ISSUE-0064`, `ISSUE-0034`, `ISSUE-0019`, `ISSUE-0036`, `ISSUE-0042`, `ISSUE-0044`, `ISSUE-0041`.  
Wave 8: `UPDATEV2-0028`.

Total unique issues: 41.

## 2026-07-10 Data Health Closure Checkpoint

`ISSUE-0035` is closed with checksum-backed source, tests, UI, export, build and browser evidence under `evidence/final/`. The final responsive UI correction was verified at desktop and 1040px widths; the Computer Use URL-confidence failure remains recorded as a limitation and no Computer Use pass is claimed.

## 2026-07-10 Independent Review Reopening Checkpoint

The restarted review agent found substantive gaps in the three earlier evaluator-ready checkpoints: missing candle evidence in `UPDATEV2-0028`, missing persisted source IDs in `UPDATEV2-0022` and insufficient direct exception-path evidence in `ISSUE-0069`. Those records were reopened in `configs/closure_matrix.yaml` and trackers; their prior evidence is retained only as a rejected checkpoint. The evaluator now reports 1/41 ready and 40 still open.

## 2026-07-10 Closure Checkpoint

Task 23 is retained as a historical rejected checkpoint: `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` were reopened after independent review. The current evaluator state is 1/41 ready and 40 still open; SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index-methodology and provider-backed workflows remain open without their complete fixture/parser/UI/export/browser gates.

## 2026-07-11 Trust Policy Review-Fix Checkpoint

The second reliability review identified end-to-end bearer/API-key redaction gaps, source-less/model score eligibility gaps, permissive unavailable-marker validation and missing conflict/full-holdings export regressions. Tests were added first and now pass: source-less, non-OK and `model:*` components cannot affect the deterministic evidence score; model rows remain visible as advisory confirmation; audit validation requires an explicit unavailable marker; session and audit paths redact env-prefixed keys, access tokens, client secrets and bearer values; the audit regression asserts conflict artefacts and the complete configured holdings summary. A fresh rebuild, package smoke and browser run are still required before updating closure dossiers.

## 2026-07-11 Follow-Up Review Fix Checkpoint

The follow-up review found JSON-string secret leaks in session and workflow redactors, acceptance of an unknown score source prefix, ambiguous model authority labelling, a candle artefact that was not declared in the audit manifest, and weak holdings assertions. These were fixed with test-first coverage. The full regression now passes 262 tests, compileall and scoped Ruff pass, and a second fresh rebuild plus packaged browser/archive verification is required before any closure dossier is updated.

## Wave Gate Commands

At every wave gate run the wave's focused tests plus:

```powershell
.\.venv\Scripts\python.exe -m compileall -q scripts src tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_app.py --smoke
```

At waves 3, 5, 6, 7 and 8 also run:

```powershell
.\scripts\build_windows.bat
.\.venv\Scripts\python.exe scripts\smoke_app.py --mode source --port 8580
.\.venv\Scripts\python.exe scripts\smoke_app.py --mode native --port 8581
.\.venv\Scripts\python.exe scripts\smoke_app.py --mode portable-native --port 8582
```

Browser/computer-use evidence must cover the pages and actions changed in that wave. Playwright/browser failure does not convert to pass through HTTP-only fallback; retry browser/Chrome/computer-use and leave UI-required gates open until rendered evidence exists.

## Interruption Protocol

Before a turn ends or a usage limit interrupts execution:

1. Finish or revert only the current incomplete atomic file edit; never leave a half-written schema migration.
2. Run the smallest test proving the current on-disk state imports.
3. Update `RUN_STATE.json` with wave, task, step, last command/result, first failing criterion and exact next command.
4. Append progress, failures and decisions to worklogs.
5. Record any live process IDs and whether they must be stopped on resume.
6. Do not mark an issue closed merely because the remaining limit is low.

## Final Completion Output

The final response must report:

1. Tool/MCP/dependency status.
2. Baseline and final test counts.
3. All 41 issue states with closure evidence links.
4. Implemented source, schemas, parsers, routes and migrations.
5. Official fixture URLs/checksums and parser outcomes.
6. Exact commands and pass/fail history.
7. Browser, Chrome, screenshot and computer-use evidence.
8. Source/native/portable build and launcher results.
9. Audit ZIP/checksum/secret-scan result.
10. Files changed and backup manifests.
11. No-Git/no-commit status unless a real repository appeared.
12. Remaining issues and exact resume prompt only if any gate did not close.

## 2026-07-11 Final Execution Checkpoint

- Completed the planned fresh rebuild and verification after the follow-up trust-policy fixes.
- Source regression, compileall, scoped Ruff, source/native/portable smoke, root launcher start/reuse, corrected package-cwd launcher start/reuse/fallback, Chrome route/workflow smoke and audit ZIP validation all passed. Computer Use was attempted but stopped by the Windows URL-confidence policy and is recorded as a limitation.
- Closure evaluator result: 4 ready, 37 still open. The three reopened records `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` now meet all current evaluator gates and were moved to closed; `ISSUE-0035` was already closed. Task 23 is therefore complete as a partial, evidence-backed closure, not as an all-41 closure.
- Strict parser/provider workflows and every other non-ready record remain open. No documentation-only or shared-evidence shortcut was used to close them.
- Durable state is in `RUN_STATE.json`, `RUN_LOG.md`, `.ai_worklog\*` and `HANDOFF.md`. No Git repository exists and no commit was created.
