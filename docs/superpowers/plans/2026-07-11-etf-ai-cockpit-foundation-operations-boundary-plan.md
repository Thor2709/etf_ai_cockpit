# Foundation, Operations and Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` with a fresh implementer and a fresh reviewer for each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing session trace, atomic I/O and closure matrix into the authoritative operational, recovery, verification and execution-boundary foundation required by `REL-01` through `REL-04`, `FUTURE-01` and `FUTURE-03`.

**Architecture:** Keep `core/atomic_io.py` as the only mutable-store commit primitive and `core/session_log.py` as the single operational trace. Introduce typed operation/evidence records around those foundations, then make release and static boundary checks consume the same records rather than inventing parallel state.

**Tech Stack:** Python 3.13, Pydantic, JSONL, DuckDB/Parquet, PyArrow, pytest, Hypothesis, Ruff, Flet, existing launcher and PyInstaller scripts.

## Global Constraints

- No scope drift; do not create broker, order, credential or external-upload functionality.
- Evidence, analysis, research state, portfolio review and user decisions stay separate; `execution_allowed` remains `false`.
- Preserve `data/universe_store.py`, `core/atomic_io.py`, Data Health, provider/evidence contracts, session trace, audit manifests, router and Flet shell.
- Use narrow adapters and migrations; do not perform unrelated refactoring.
- Before the verified Wave 0 Task 2 boundary, do not initialise Git, create a worktree, commit, push, create a pull request, delete user data or modify a remote service. After Task 2 independent approval, the user's explicit version-control authorisation permits only the local baseline Git setup and optional private GitHub push; no Task 3 implementation may begin in that handoff.
- Tests must prove observable behaviour and failure paths; one mock-call assertion is insufficient.
- Record a RED command before behavioural code, a GREEN command afterwards, then refactor and rerun the focused regression.
- Visible controls reuse the existing dark research-cockpit vocabulary and expose semantic, keyboard and state behaviour.
- No issue state changes until fresh source, migration, test, package, browser, audit and independent-review evidence exists.
- Store task reports in the progress ledger, `RUN_STATE.json`, `.ai_worklog` and the closure matrix only after evidence exists.

---

## File structure and interfaces

| File | Responsibility |
|---|---|
| Modify `src/etf_cockpit/core/session_log.py:1-276` | Versioned event records, hash-chain continuity, safe tail recovery and redaction integration |
| Create `src/etf_cockpit/operations/models.py` | `OperationalEvent`, `VerificationRun`, `ClosureEvidenceRecord`, `WriteTransaction` Pydantic models |
| Create `src/etf_cockpit/operations/event_store.py` | Append/index/query adapter over the existing session log |
| Create `src/etf_cockpit/operations/recovery.py` | Startup transaction scan and deterministic recovery classification |
| Modify `src/etf_cockpit/core/atomic_io.py:1-366` | Register grouped write transaction lifecycle using existing locks/journals/backups |
| Modify `src/etf_cockpit/core/closure.py:1-133`, `configs/closure_matrix.yaml` | Version-2 programme records, stale-evidence checks and independent-review requirement |
| Create `src/etf_cockpit/governance/static_checks.py` | Context-aware execution/rejection/static package report |
| Create `configs/rejection_registry.yaml` and `docs/architecture/future/*.md` | Machine-readable permanent rejections and future-only design records |
| Create `scripts/verify_issue.py`, `scripts/verify_clean_environment.ps1` | Evidence collection without auto-closing issues |
| Test `tests/operations/`, `tests/scope_boundary/`, `tests/release/` | Fault, trace, closure and boundary behaviour |

**Public interfaces produced before later plans run:**

```python
class VerificationRun(BaseModel):
    verification_run_id: str
    verification_type: str
    command: str
    source_hash: str
    result: Literal["pass", "fail", "blocked"]
    exit_code: int
    output_paths: list[str]
    output_checksums: list[str]
    issue_ids: list[str]

class ClosureEvidenceRecord(BaseModel):
    closure_evidence_id: str
    issue_id: str
    requirement_version: str
    verification_run_ids: list[str]
    independent_reviewer: str
    review_result: Literal["approved", "rejected"]
    evidence_hash: str

def run_static_execution_boundary_check(root: Path) -> ExecutionBoundaryReport: ...
def recover_incomplete_transactions(data_root: Path) -> list[RecoveryResult]: ...
```

### Task 1: Establish typed verification and closure evidence records

**Files:**

- Create: `src/etf_cockpit/operations/__init__.py`, `src/etf_cockpit/operations/models.py`, `tests/operations/test_verification_records.py`, `tests/release/test_issue_evidence.py`
- Modify: `src/etf_cockpit/core/closure.py:1-133`, `configs/closure_matrix.yaml:1-end`, `tests/test_closure_matrix.py:1-end` (migration of the existing exact-41 regression to assert 42 active records while preserving the historic 41-ID baseline)

**Consumes:** existing `ClosureMatrix` parser and the 41-record list.

**Produces:** versioned evidence records which later plans attach to without changing issue state.

- [x] **Step 1: Write the failing evidence-validation tests**

```python
def test_closure_evidence_rejects_builder_as_required_independent_reviewer() -> None:
    with pytest.raises(ValidationError, match="independent_reviewer"):
        ClosureEvidenceRecord(
            closure_evidence_id="ce-1", issue_id="DATA-05", requirement_version="2026-07-11",
            verification_run_ids=["vr-1"], builder="implementer", independent_reviewer="implementer",
            review_result="approved", evidence_hash="a" * 64,
        )

def test_new_data05_record_does_not_rewrite_the_historic_41_baseline() -> None:
    matrix = load_closure_matrix(path)
    assert matrix.programme_schema_version == 2
    assert matrix.historic_baseline_count == 41
    assert matrix.record_for("DATA-05").status == "still_open"
```

- [x] **Step 2: Run the focused RED suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py -q`

Expected: FAIL because the `operations` models and DATA-05 closure record do not yet exist.

- [x] **Step 3: Create the minimal typed models and schema-2 matrix parser**

```python
class ClosureEvidenceRecord(BaseModel):
    closure_evidence_id: str
    issue_id: str
    requirement_version: str
    verification_run_ids: list[str]
    builder: str
    independent_reviewer: str
    review_result: Literal["approved", "rejected"]
    evidence_hash: str

    @model_validator(mode="after")
    def require_independent_reviewer(self) -> Self:
        if self.review_result == "approved" and self.builder == self.independent_reviewer:
            raise ValueError("independent_reviewer must differ from builder")
        return self
```

Set `programme_schema_version: 2`, `historic_baseline_count: 41`, and create a `DATA-05` record with `still_open` status and the source/schema/tests/UI/audit/package/browser gates specified in the approved specification.

- [x] **Step 4: Run focused GREEN and regression checks**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q`

Expected: PASS, with the historical 41 count preserved and 42 active records explicitly represented.

- [x] **Step 5: Record the non-Git checkpoint**

Update the programme ledger, `RUN_STATE.json`, `.ai_worklog/PLAN.md` and `.ai_worklog/TESTING.md` with command, exit code, source checksum and the new matrix schema version. No commit step is permitted because the repository is not Git-backed.

### Task 2: Make the session trace the operational event authority

**Dependency resolution:** The foundation interface table requires `OperationalEvent`, but the completed Task 1 brief only produced verification and closure-evidence records. Task 2 therefore owns the narrow addition of `OperationalEvent` to `operations/models.py`; this preserves the approved single-model-module interface without reopening the independently reviewed Task 1 deliverable.

**Files:**

- Create: `src/etf_cockpit/operations/event_store.py`, `tests/operations/test_operational_events.py`, `tests/operations/test_event_store.py`, `tests/operations/test_redaction.py`
- Modify: `src/etf_cockpit/operations/__init__.py:1-end` (export the new public type), `src/etf_cockpit/operations/models.py:1-end` (add the typed `OperationalEvent` consumed by this task only), `src/etf_cockpit/core/session_log.py:1-276`, `src/etf_cockpit/core/workflow.py:67-211` (remove the default secondary workflow log while retaining the explicit test/adapter seam), `src/etf_cockpit/app/state.py:1-358`, `src/etf_cockpit/app/pages/diagnostics.py:1-end`, `src/etf_cockpit/app/pages/dashboard.py:206` (name the canonical session trace), `tests/test_workflow_runtime.py:1-end` (authority and visible-path regressions)

**Consumes:** Task 1 verification/closure records and the existing `session.jsonl` redaction.

**Produces:** typed `OperationalEvent` records and one event stream from UI action through workflow, files and audit outputs.

**Task interface:**

```python
class OperationalEvent(BaseModel):
    event_id: str
    session_id: str
    sequence_number: int
    timestamp_utc: datetime
    event_type: str
    status: str | None = None
    component: str | None = None
    action_id: str | None = None
    prior_event_hash: str | None = None
    event_hash: str | None = None

def load_events_with_tail_recovery(path: Path) -> tuple[list[OperationalEvent], TailRecovery]: ...
def append_operational_event(event: OperationalEvent, *, path: Path = SESSION_LOG_PATH) -> None: ...
def current_activity_view(events: Iterable[OperationalEvent]) -> ActivityView: ...
```

New writes must populate `event_id`, `prior_event_hash` and `event_hash`; the loader may represent pre-existing valid rows without those fields as legacy records, but must never silently discard a valid complete row.

- [x] **Step 1: Write RED tests for ordering, tail recovery and state derivation**

```python
def test_event_store_recovers_only_the_incomplete_jsonl_tail(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(valid_event_json + "\n" + '{"event_id":', encoding="utf-8")
    events, recovery = load_events_with_tail_recovery(path)
    assert [event.event_id for event in events] == ["event-1"]
    assert recovery.quarantined_tail is True

def test_ui_activity_is_derived_from_workflow_events() -> None:
    state = build_state_with_events([queued_event, completed_event])
    assert state.current_activity_view().status == "completed"
```

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py -q`

Expected: FAIL because no typed event-store loader or activity projection exists.

- [x] **Step 3: Implement the event adapter without replacing the current JSONL store**

```python
def append_operational_event(event: OperationalEvent, *, path: Path = SESSION_LOG_PATH) -> None:
    append_event(event.model_dump(mode="json"), path=path)

def current_activity_view(events: Iterable[OperationalEvent]) -> ActivityView:
    latest = max(events, key=lambda item: item.sequence_number, default=None)
    return ActivityView.from_event(latest)
```

Preserve existing nested secret redaction. Append sequence number, prior-event hash and current-event hash before the write, but retain graceful logging failure behaviour.

- [x] **Step 4: Run GREEN plus diagnostics regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py tests\test_trust_critical_artifacts.py -q`

Expected: PASS; diagnostics still renders a redacted, readable session trace.

- [x] **Step 5: Record a reviewer-ready deliverable**

Store a JSONL fixture checksum, a diagnostics screenshot/semantic capture plan and the review package range in the ledger. A separate reviewer must verify that no competing mutable activity store remains authoritative.

### Task 3: Route mutable canonical writes through the existing atomic transaction primitive

**Files:**

- Create: `src/etf_cockpit/operations/recovery.py`, `tests/operations/test_transactions.py`, `tests/operations/test_recovery.py`, `tests/operations/test_backups.py`
- Modify: `src/etf_cockpit/core/atomic_io.py:1-366`, `src/etf_cockpit/core/migrations.py:1-145`, selected mutable writer modules only after a writer inventory is generated

**Consumes:** Tasks 1-2 evidence/event contracts and existing grouped atomic write/journal APIs.

**Produces:** `WriteTransaction` lifecycle and startup recovery result reused by registry, catalogue, portfolio and workflow tasks.

- [x] **Step 1: Write parameterised fault-injection RED tests**

```python
@pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
def test_recovery_exposes_old_or_new_complete_generation_only(tmp_path: Path, crash_point: str) -> None:
    simulate_grouped_write_crash(tmp_path, crash_point=crash_point)
    outcome = recover_incomplete_transactions(tmp_path)
    assert outcome[0].state in {"rolled_back", "recovery_required"}
    assert read_current_pointer(tmp_path) in {"generation-old", "generation-new"}
```

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\test_atomic_io.py -q`

Expected: FAIL because transaction records and recovery classification are absent.

- [x] **Step 3: Implement transaction records around, not beside, `atomic_io`**

```python
def begin_write_transaction(*, transaction_type: str, base_generations: dict[str, str]) -> WriteTransaction: ...
def mark_transaction_ready(transaction_id: str, checksums: dict[str, str]) -> WriteTransaction: ...
def recover_incomplete_transactions(data_root: Path) -> list[RecoveryResult]: ...
```

Each function delegates actual byte/group commit, lock, journal, verification and backup work to `core.atomic_io`; it never introduces a second lock or journal format. Startup recovery must select normal, read-only diagnostic or recovery-required mode without promoting ambiguous staging data.

- [x] **Step 4: Run GREEN and restore drill**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py -q`

Expected: PASS, including locked-file, checksum-mismatch and restore fixtures.

- [x] **Step 5: Log recovery evidence**

Write the fault matrix and backup manifest checksums to the wave evidence directory; recovery-state screenshots are not applicable because Task 3 adds no user-visible surface, as recorded in the task report. Update the ledger but do not close `REL-02` until package recovery has also passed.

Task 3 implementation, five fix-pass evidence records and the fresh independent approval are recorded in `.ai_worklog/task-3-report.md`, `.ai_worklog/task-3-fix-pass-2-report.md`, `.ai_worklog/task-3-fix-pass-3-report.md`, `.ai_worklog/task-3-fix-pass-4-report.md`, `.ai_worklog/task-3-fix-pass-5-report.md` and `.ai_worklog/task-3-review-final2.md`. The task-level review gate passed with no Critical, Important or Minor findings. PR `https://github.com/Thor2709/etf_ai_cockpit/pull/1` merged the branch at `046e3bbfe9cab41f6cfec59547f540bce85b2c44`; post-merge focused tests, Ruff, compileall and source smoke passed. Task 4 is now the next dependency-valid task; `ISSUE-0040` remains open for its later UI/package/browser gates.

### Task 4: Enforce the no-execution and rejection boundary

**Files:**

- Create: `src/etf_cockpit/governance/static_checks.py`, `configs/rejection_registry.yaml`, `docs/architecture/future/execution_scope_and_approval.md`, `docs/architecture/future/broker_adapter_contract.md`, `docs/architecture/future/source_of_truth_and_reconciliation.md`, `tests/scope_boundary/test_execution_boundary.py`, `tests/scope_boundary/test_rejection_registry.py`, `tests/scope_boundary/test_package_inventory.py`
- Modify: `src/etf_cockpit/core/types.py:1-131`, audit/release scripts as required by the report interface

**Consumes:** Task 1 closure evidence and existing `executable_authority=false` fields.

**Produces:** `ExecutionBoundaryReport` and static rejection checks consumed by governance and release tasks.

- [x] **Step 1: Write RED mutation tests**

```python
def test_production_place_order_symbol_is_a_boundary_violation(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("def place_order(): pass\n", encoding="utf-8")
    report = run_static_execution_boundary_check(tmp_path)
    assert report.result == "fail"
    assert report.violations[0].code == "PROHIBITED_ORDER_SYMBOL"

def test_sort_order_is_not_a_false_positive(tmp_path: Path) -> None:
    (tmp_path / "safe.py").write_text("sort_order = 'asc'\n", encoding="utf-8")
    assert run_static_execution_boundary_check(tmp_path).result == "pass"
```

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\scope_boundary\test_execution_boundary.py tests\scope_boundary\test_rejection_registry.py -q`

Expected: FAIL because the checker and registry do not exist.

- [x] **Step 3: Implement context-aware AST/config/dependency/resource scans**

```python
class ExecutionBoundaryReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    result: Literal["pass", "fail"]
    violations: list[BoundaryViolation]
    scanned_files: int
    policy_checksum: str
    generated_at: datetime
```

Allow future-only documentation and test fixtures by explicit path allow-list. Reject broker SDKs, order-routing symbols, credential/order endpoints, current UI order controls and any schema value with `execution_allowed=True`.

- [x] **Step 4: Run GREEN and release-hardening regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\scope_boundary tests\test_release_hardening.py -q`

Expected: PASS; a real production tree produces a machine-readable passing report and the injected violations fail.

- [x] **Step 5: Create future-only documentation evidence**

Each future architecture document begins with the approved future-only/no-authority banner, has no credentials or runnable order examples, and is linked from System Map only after the governance plan supplies that route.

Task 4 implementation and its post-merge generated-package correction are
independently approved. The implementation was merged through PR 2 at
`0f2b2cb`; the post-merge correction was merged through PR 3 at `5b732e4`.
Final clean-main verification passed the 54-test scope/release bundle, the
75-test release/operations bundle, the static scan (358 files, zero
violations), and source smoke. No local issue moved to closed: `ISSUE-0040`
and later tracker records still require their complete issue-specific gates.

### Task 5: Build evidence automation without automatic issue closure

**Files:**

- Create: `scripts/verify_issue.py`, `scripts/verify_clean_environment.ps1`, `tests/release/test_clean_environment.py`, `tests/release/test_package_matrix.py`
- Modify: `scripts/dev_finish_check.py:1-end`, `configs/closure_matrix.yaml:1-end`, `README_FIRST_RUN.md:1-end`

**Consumes:** Tasks 1-4 record models and static report.

**Produces:** fresh verification packages that a separate reviewer approves or rejects.

- [x] **Step 1: Write RED tests for stale/missing/falsified evidence**

```python
def test_verify_issue_rejects_a_passing_result_from_a_different_source_hash(tmp_path: Path) -> None:
    result = verify_issue("DATA-05", source_hash="new", evidence_root=tmp_path)
    assert result.status == "blocked"
    assert "source hash" in result.limitations[0]

def test_verify_issue_never_updates_tracker_state(monkeypatch: pytest.MonkeyPatch) -> None:
    assert verify_issue("ISSUE-0013").tracker_mutated is False
```

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\release\test_clean_environment.py tests\release\test_package_matrix.py tests\operations\test_verification_records.py -q`

Expected: FAIL because no verification command builds a typed evidence package.

- [x] **Step 3: Implement fixed command selection and manifest capture**

`verify_issue.py` reads only the matrix-declared commands, stores stdout/stderr paths and SHA-256 checksums, records source/environment hashes, and returns a `VerificationRun`. It may never write `issues/open.md`, `issues/closed.md` or a closure status.

- [x] **Step 4: Run GREEN plus current source baseline**

Run: `.\.venv\Scripts\python.exe -m pytest tests\release tests\operations -q`

Expected: PASS. Then run `.\scripts\verify_clean_environment.ps1` only after all its package dependencies are explicitly present; otherwise record its exact blocked result without treating it as a pass.

- [x] **Step 5: Complete wave review package**

The fresh reviewer receives the wave task reports, static-boundary JSON, fault matrix, closure-matrix diff and current source hash. Resolve every Critical or Important finding before the next wave begins.

### Task 5 completion checkpoint - 2026-07-12

Task 5 was implemented on `wave0/task5-evidence-automation`, independently
reviewed, corrected for five Important fail-open findings, re-reviewed and
merged through PR 4 (`https://github.com/Thor2709/etf_ai_cockpit/pull/4`) at
`fc4d61cfc6e77da9a91aeb5afe0341b1d7658f55`. The implementation provides
source/environment-bound, fresh, checksum-validated, deterministic and
read-only issue evidence verification; fail-closed clean-environment,
package and Chrome stages; and deterministic package-mode declarations.

Fresh post-merge evidence: focused Task 5/review-record tests 31 passed;
release and operations suites 26 and 81 passed; Ruff, compileall, pip check
and PowerShell AST parsing passed; source smoke returned
`snapshot_ok as_of=2026-07-09 signals=16 backtests=5`. A clean-environment
execution requiring a fresh venv, package build and Chrome was not run because
it would create machine-specific artefacts; its missing-tool paths are
explicitly blocked and tested. No issue moved between the local ledgers;
`UPDATEV2-0029`, `ISSUE-0013`, `ISSUE-0014` and `ISSUE-0045` remain open for
their complete later release/UI/browser closure gates. The independent
re-review is `.ai_worklog/task-5-review-rereview.md` with no Critical or
Important findings. `execution_allowed` remains `false`.

### GitHub issue synchronisation checkpoint - 2026-07-12

The authoritative local issue inventory was synchronised to
`Thor2709/etf_ai_cockpit` after Wave 0 Task 5 integration. The versioned
manifest `issues/github_issue_map.json` contains 98 unique stable IDs (77
selected open and 21 selected closed), each mapped to one canonical GitHub
issue with a source checksum. The final apply and read-back reconciliation
passed with matching 77/21 state counts and no unresolved duplicates. Exact
stable-ID duplicate records were retained and closed as duplicates; no GitHub
issue was deleted. The synchroniser's seven-test release slice and Ruff check
passed. No local issue moved between `issues/open.md` and `issues/closed.md`.
The next dependency-valid implementation remains Wave 1 Governance Task 1.
