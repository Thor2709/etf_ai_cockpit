# Task 1 final task re-review package - no-Git task base to current workspace

## Review basis
- Base: immutable Task 1 snapshot captured before fresh implementation; no Git repository or commit exists.
- Head: current workspace after the actor-validation fix and Round-2 checkpoint-evidence correction.
- Scope: Task 1 and both Important review findings. Ignore generated __pycache__ files.
- The metadata-validation Minor remains in the ledger for final triage and was not changed.
- tests/test_closure_matrix.py entered scope after pre-task snapshot; its reconstructed base normalises line endings and original manifest remains at .ai_worklog/task-1-code-manifest-before.csv.

## Diff: src/etf_cockpit/core/closure.py
```diff
diff --git a/.ai_worklog/task-1-base/src/etf_cockpit/core/closure.py b/src/etf_cockpit/core/closure.py
index cb8a19d..3990a07 100644
--- a/.ai_worklog/task-1-base/src/etf_cockpit/core/closure.py
+++ b/src/etf_cockpit/core/closure.py
@@ -1,22 +1,34 @@
 from __future__ import annotations
 
 from dataclasses import dataclass
 import hashlib
 from pathlib import Path, PurePosixPath
 import re
-from typing import Any
+from typing import Any, Iterator
 
 import yaml
 
 
-VALID_GATES = frozenset({"source", "tests", "ui", "export", "build", "browser"})
+VALID_GATES = frozenset(
+    {
+        "source",
+        "schema",
+        "tests",
+        "ui",
+        "audit",
+        "export",
+        "package",
+        "build",
+        "browser",
+    }
+)
 VALID_STATUSES = frozenset({"still_open", "closed", "blocked", "deferred"})
 
 
 @dataclass(frozen=True)
 class ClosureCriterion:
     criterion_id: str
     text: str
     required_gates: tuple[str, ...]
     evidence_paths: tuple[str, ...] = ()
 
@@ -31,20 +43,42 @@ class IssueClosureRecord:
 
 
 @dataclass(frozen=True)
 class ClosureEvaluation:
     issue_id: str
     ready: bool
     missing_gates: tuple[str, ...]
     evidence_paths: tuple[str, ...]
 
 
+@dataclass(frozen=True)
+class ClosureMatrix:
+    programme_schema_version: int
+    historic_baseline_count: int
+    records: tuple[IssueClosureRecord, ...]
+
+    def __iter__(self) -> Iterator[IssueClosureRecord]:
+        return iter(self.records)
+
+    def __len__(self) -> int:
+        return len(self.records)
+
+    def __getitem__(self, index: int) -> IssueClosureRecord:
+        return self.records[index]
+
+    def record_for(self, issue_id: str) -> IssueClosureRecord:
+        for record in self.records:
+            if record.issue_id == issue_id:
+                return record
+        raise KeyError(issue_id)
+
+
 def _require_text(value: Any, field: str) -> str:
     if not isinstance(value, str) or not value.strip():
         raise ValueError(f"{field} must be a non-empty string")
     return value.strip()
 
 
 def _parse_criterion(raw: Any, issue_id: str) -> ClosureCriterion:
     if not isinstance(raw, dict):
         raise ValueError(f"{issue_id} criteria must be mappings")
     criterion_id = _require_text(raw.get("criterion_id"), "criterion_id")
@@ -60,25 +94,32 @@ def _parse_criterion(raw: Any, issue_id: str) -> ClosureCriterion:
 
 
 def _normalise_evidence_path(value: Any) -> str:
     path = _require_text(value, "evidence path").replace("\\", "/")
     parsed = PurePosixPath(path)
     if parsed.is_absolute() or ".." in parsed.parts or re.match(r"^[A-Za-z]:/", path):
         raise ValueError(f"evidence path must be relative to the evidence root: {path}")
     return parsed.as_posix()
 
 
-def load_closure_matrix(path: Path) -> list[IssueClosureRecord]:
+def load_closure_matrix(path: Path) -> ClosureMatrix:
     raw = yaml.safe_load(path.read_text(encoding="utf-8"))
     if not isinstance(raw, dict) or not isinstance(raw.get("issues"), list):
         raise ValueError("closure matrix must contain an issues list")
 
+    programme_schema_version = raw.get("programme_schema_version", raw.get("schema_version", 1))
+    if isinstance(programme_schema_version, bool) or not isinstance(programme_schema_version, int):
+        raise ValueError("programme_schema_version must be an integer")
+    historic_baseline_count = raw.get("historic_baseline_count", len(raw["issues"]))
+    if isinstance(historic_baseline_count, bool) or not isinstance(historic_baseline_count, int):
+        raise ValueError("historic_baseline_count must be an integer")
+
     records: list[IssueClosureRecord] = []
     seen_issues: set[str] = set()
     seen_criteria: set[str] = set()
     for item in raw["issues"]:
         if not isinstance(item, dict):
             raise ValueError("each issue must be a mapping")
         issue_id = _require_text(item.get("issue_id"), "issue_id")
         if issue_id in seen_issues:
             raise ValueError(f"duplicate issue_id: {issue_id}")
         seen_issues.add(issue_id)
@@ -97,21 +138,25 @@ def load_closure_matrix(path: Path) -> list[IssueClosureRecord]:
             raise ValueError(f"{issue_id} wave must be a positive integer")
         records.append(
             IssueClosureRecord(
                 issue_id=issue_id,
                 title=_require_text(item.get("title"), "title"),
                 wave=wave,
                 criteria=criteria,
                 status=status,
             )
         )
-    return records
+    return ClosureMatrix(
+        programme_schema_version=programme_schema_version,
+        historic_baseline_count=historic_baseline_count,
+        records=tuple(records),
+    )
 
 
 def _gate_for_path(path: str) -> str | None:
     parts = PurePosixPath(path.replace("\\", "/")).parts
     return parts[0] if parts and parts[0] in VALID_GATES else None
 
 
 def evaluate_issue(record: IssueClosureRecord, evidence_root: Path) -> ClosureEvaluation:
     evidence_paths = tuple(
         dict.fromkeys(path for criterion in record.criteria for path in criterion.evidence_paths)
```

## Diff: configs/closure_matrix.yaml
```diff
diff --git a/.ai_worklog/task-1-base/configs/closure_matrix.yaml b/configs/closure_matrix.yaml
index ff2749e..5c4950d 100644
--- a/.ai_worklog/task-1-base/configs/closure_matrix.yaml
+++ b/configs/closure_matrix.yaml
@@ -1,11 +1,12 @@
-schema_version: 1
+programme_schema_version: 2
+historic_baseline_count: 41
 issues:
 - issue_id: ISSUE-0067
   title: Local score history and per-instrument score evolution mini charts
   wave: 7
   status: still_open
   criteria:
   - criterion_id: ISSUE-0067-R01
     text: 'Acceptance criteria: Each completed score-generation run appends a new local score snapshot for every scored ETF/stock.'
     required_gates:
     - source
@@ -4447,10 +4448,50 @@ issues:
   - criterion_id: ISSUE-0068-C-BROWSER
     text: Rebuilt app starts and local UI smoke test passes.
     required_gates:
     - browser
     evidence_paths: []
   - criterion_id: ISSUE-0068-C-LIMITS
     text: Remaining limitations recorded.
     required_gates:
     - source
     evidence_paths: []
+- issue_id: DATA-05
+  title: Verified 39-exposure coverage and independently addressable EU technology subareas
+  wave: 3
+  status: still_open
+  criteria:
+  - criterion_id: DATA-05-C-SOURCE
+    text: Current official and provider identity evidence is recorded for every authorised seed.
+    required_gates:
+    - source
+    evidence_paths: []
+  - criterion_id: DATA-05-C-SCHEMA
+    text: The versioned registry schema represents every required DATA-05 identity and coverage field.
+    required_gates:
+    - schema
+    evidence_paths: []
+  - criterion_id: DATA-05-C-TESTS
+    text: All 39 exposures, 25 EU technology subareas and the 8/9/8 balance are verified by tests.
+    required_gates:
+    - tests
+    evidence_paths: []
+  - criterion_id: DATA-05-C-UI
+    text: Coverage screens and stable deep links expose every EU technology subarea.
+    required_gates:
+    - ui
+    evidence_paths: []
+  - criterion_id: DATA-05-C-AUDIT
+    text: Audit manifests contain coverage, verification, discrepancy and corporate-event evidence.
+    required_gates:
+    - audit
+    evidence_paths: []
+  - criterion_id: DATA-05-C-PACKAGE
+    text: The packaged application preserves the verified DATA-05 coverage behaviour.
+    required_gates:
+    - package
+    evidence_paths: []
+  - criterion_id: DATA-05-C-BROWSER
+    text: Source and packaged browser journeys verify required venues and coverage bands.
+    required_gates:
+    - browser
+    evidence_paths: []
```

## Diff: tests/test_closure_matrix.py
```diff
diff --git a/.ai_worklog/task-1-base/tests/test_closure_matrix.py b/tests/test_closure_matrix.py
index ea4d337..2afb7d2 100644
--- a/.ai_worklog/task-1-base/tests/test_closure_matrix.py
+++ b/tests/test_closure_matrix.py
@@ -59,25 +59,30 @@ EXPECTED_41_IDS = {
 def write_evidence(root: Path, relative_path: str, content: bytes = b"verified") -> None:
     target = root / relative_path
     target.parent.mkdir(parents=True, exist_ok=True)
     target.write_bytes(content)
     target.with_name(target.name + ".sha256").write_text(
         hashlib.sha256(content).hexdigest() + "\n",
         encoding="ascii",
     )
 
 
-def test_closure_matrix_contains_exactly_the_reviewed_41_issue_ids():
-    records = load_closure_matrix(Path("configs/closure_matrix.yaml"))
-
-    assert len(records) == 41
-    assert {record.issue_id for record in records} == EXPECTED_41_IDS
+def test_closure_matrix_preserves_reviewed_41_ids_and_adds_data05_separately():
+    matrix = load_closure_matrix(Path("configs/closure_matrix.yaml"))
+    records = tuple(matrix)
+
+    assert matrix.programme_schema_version == 2
+    assert matrix.historic_baseline_count == 41
+    assert len(records) == 42
+    assert {record.issue_id for record in records} == EXPECTED_41_IDS | {"DATA-05"}
+    assert {record.issue_id for record in records if record.issue_id != "DATA-05"} == EXPECTED_41_IDS
+    assert matrix.record_for("DATA-05").status == "still_open"
     assert all(record.criteria for record in records)
     assert all(
         not criterion.text.lstrip().startswith("- ")
         for record in records
         for criterion in record.criteria
     )
     assert all(
         ";" not in criterion.text
         for record in records
         for criterion in record.criteria
@@ -218,18 +223,18 @@ issues:
 def test_matrix_rejects_non_positive_wave(tmp_path):
     matrix = tmp_path / "matrix.yaml"
     matrix.write_text(
         """
 issues:
   - issue_id: ISSUE-TEST
     title: Invalid wave
     wave: 0
     criteria:
       - criterion_id: ISSUE-TEST-01
-        text: Reject unsafe paths.
+        text: Wave must be positive.
         required_gates: [source]
 """,
         encoding="utf-8",
     )
 
     with pytest.raises(ValueError, match="positive integer"):
         load_closure_matrix(matrix)
```

## New file: src/etf_cockpit/operations/__init__.py
```python
"""Typed operational and verification records."""

from etf_cockpit.operations.models import ClosureEvidenceRecord, VerificationRun

__all__ = ["ClosureEvidenceRecord", "VerificationRun"]

```

## New file: src/etf_cockpit/operations/models.py
```python
from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, model_validator


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
    builder: str
    independent_reviewer: str
    review_result: Literal["approved", "rejected"]
    evidence_hash: str

    @model_validator(mode="after")
    def require_independent_reviewer(self) -> Self:
        if self.review_result == "approved":
            self.builder = self.builder.strip()
            self.independent_reviewer = self.independent_reviewer.strip()
            if not self.builder:
                raise ValueError("builder must be non-empty for approved closure evidence")
            if not self.independent_reviewer:
                raise ValueError(
                    "independent_reviewer must be non-empty for approved closure evidence"
                )
            if self.builder == self.independent_reviewer:
                raise ValueError("independent_reviewer must differ from builder")
        return self

```

## New file: tests/operations/test_verification_records.py
```python
import pytest
from pydantic import ValidationError

from etf_cockpit.operations.models import ClosureEvidenceRecord, VerificationRun


def test_verification_run_records_reproducible_result_metadata() -> None:
    record = VerificationRun(
        verification_run_id="vr-1",
        verification_type="focused_tests",
        command="python -m pytest tests/operations -q",
        source_hash="a" * 64,
        result="pass",
        exit_code=0,
        output_paths=["tests/task-1.txt"],
        output_checksums=["b" * 64],
        issue_ids=["DATA-05"],
    )

    assert record.result == "pass"
    assert record.issue_ids == ["DATA-05"]


def test_verification_run_rejects_unknown_result() -> None:
    with pytest.raises(ValidationError, match="result"):
        VerificationRun(
            verification_run_id="vr-1",
            verification_type="focused_tests",
            command="python -m pytest tests/operations -q",
            source_hash="a" * 64,
            result="unknown",
            exit_code=1,
            output_paths=[],
            output_checksums=[],
            issue_ids=["DATA-05"],
        )


def test_closure_evidence_rejects_builder_as_required_independent_reviewer() -> None:
    with pytest.raises(ValidationError, match="independent_reviewer"):
        ClosureEvidenceRecord(
            closure_evidence_id="ce-1",
            issue_id="DATA-05",
            requirement_version="2026-07-11",
            verification_run_ids=["vr-1"],
            builder="implementer",
            independent_reviewer="implementer",
            review_result="approved",
            evidence_hash="a" * 64,
        )


def test_approved_closure_evidence_rejects_blank_independent_reviewer() -> None:
    with pytest.raises(ValidationError, match="independent_reviewer"):
        ClosureEvidenceRecord(
            closure_evidence_id="ce-blank-reviewer",
            issue_id="DATA-05",
            requirement_version="2026-07-11",
            verification_run_ids=["vr-1"],
            builder="implementer",
            independent_reviewer="  ",
            review_result="approved",
            evidence_hash="a" * 64,
        )


def test_approved_closure_evidence_rejects_whitespace_equivalent_reviewer() -> None:
    with pytest.raises(ValidationError, match="independent_reviewer"):
        ClosureEvidenceRecord(
            closure_evidence_id="ce-whitespace-reviewer",
            issue_id="DATA-05",
            requirement_version="2026-07-11",
            verification_run_ids=["vr-1"],
            builder=" implementer ",
            independent_reviewer="implementer",
            review_result="approved",
            evidence_hash="a" * 64,
        )


def test_approved_closure_evidence_stores_normalised_actor_ids() -> None:
    record = ClosureEvidenceRecord(
        closure_evidence_id="ce-normalised-actors",
        issue_id="DATA-05",
        requirement_version="2026-07-11",
        verification_run_ids=["vr-1"],
        builder=" implementer ",
        independent_reviewer=" reviewer ",
        review_result="approved",
        evidence_hash="a" * 64,
    )

    assert record.builder == "implementer"
    assert record.independent_reviewer == "reviewer"


def test_rejected_closure_evidence_may_record_the_builder_as_reviewer() -> None:
    record = ClosureEvidenceRecord(
        closure_evidence_id="ce-2",
        issue_id="DATA-05",
        requirement_version="2026-07-11",
        verification_run_ids=["vr-1"],
        builder="implementer",
        independent_reviewer="implementer",
        review_result="rejected",
        evidence_hash="a" * 64,
    )

    assert record.review_result == "rejected"

```

## New file: tests/release/test_issue_evidence.py
```python
from pathlib import Path

from etf_cockpit.core.closure import load_closure_matrix


def test_new_data05_record_does_not_rewrite_the_historic_41_baseline() -> None:
    matrix = load_closure_matrix(Path("configs/closure_matrix.yaml"))

    assert matrix.programme_schema_version == 2
    assert matrix.historic_baseline_count == 41
    assert len(matrix) == 42
    assert matrix.record_for("DATA-05").status == "still_open"


def test_data05_requires_every_approved_closure_gate() -> None:
    matrix = load_closure_matrix(Path("configs/closure_matrix.yaml"))
    record = matrix.record_for("DATA-05")

    required_gates = {
        gate
        for criterion in record.criteria
        for gate in criterion.required_gates
    }
    assert required_gates == {
        "source",
        "schema",
        "tests",
        "ui",
        "audit",
        "package",
        "browser",
    }

```

## Current durable checkpoints
### RUN_STATE active programme
```json
{
  "name": "2026-07-11-etf-ai-cockpit-approved-programme",
  "programme_index": "docs/superpowers/plans/2026-07-11-etf-ai-cockpit-programme-index.md",
  "progress_ledger": "docs/superpowers/plans/2026-07-11-etf-ai-cockpit-progress-ledger.md",
  "phase": "wave0_task1_review_fix_verified_fresh_independent_rereview_pending",
  "next_task": "Fresh independent re-review of Wave 0, Foundation Task 1 reviewer-finding fix",
  "git_repository": false,
  "baseline": {
    "pytest": 0,
    "ruff": 0,
    "compileall": 0,
    "source_snapshot_smoke": 0,
    "source_smoke": 0,
    "native_smoke": 0,
    "portable_native_smoke": 0,
    "rendered_source_browser_inspection": "passed"
  },
  "plan_preflight": {
    "implementation_plans": 9,
    "authorised_epics": 60,
    "still_open_tracker_records_mapped_once": 37,
    "blocking_contradictions": 0,
    "implementation_started": true
  },
  "task_1_checkpoint": {
    "matrix_programme_schema_version": 2,
    "historic_baseline_count": 41,
    "active_record_count": 42,
    "data05_status": "still_open",
    "red_command": ".\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_verification_records.py tests\\release\\test_issue_evidence.py -q",
    "red_exit_code": 1,
    "green_command": ".\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_verification_records.py tests\\release\\test_issue_evidence.py tests\\test_closure_matrix.py -q",
    "green_exit_code": 0,
    "full_test_exit_code": 0,
    "source_checksums_sha256": {
      "src/etf_cockpit/operations/__init__.py": "8c8ee081d0a4fdc3e72a543702ccca1d863413fdf79ba51ff8f7f29681740e48",
      "src/etf_cockpit/operations/models.py": "77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294",
      "src/etf_cockpit/core/closure.py": "59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e",
      "configs/closure_matrix.yaml": "c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595"
    },
    "review_fix": {
      "finding": "Round-1 independent review: approved evidence accepted blank actor IDs and whitespace-equivalent builder/reviewer identities.",
      "red_command": ".\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_verification_records.py -q",
      "red_exit_code": 1,
      "green_command": ".\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_verification_records.py tests\\release\\test_issue_evidence.py tests\\test_closure_matrix.py -q",
      "green_exit_code": 0,
      "ruff_command": ".\\.venv\\Scripts\\python.exe -m ruff check src\\etf_cockpit\\operations\\models.py tests\\operations\\test_verification_records.py",
      "ruff_exit_code": 0,
      "compile_command": ".\\.venv\\Scripts\\python.exe -m compileall -q src\\etf_cockpit\\operations",
      "compile_exit_code": 0
    },
    "report": ".ai_worklog/task-1-report.md",
    "independent_review": "round_1_important_finding_fixed_fresh_independent_rereview_pending"
  }
}```
### Relevant current checkpoint excerpts
```text
## 2026-07-11 Wave 0 Task 1 Checkpoint-Evidence Correction (Round-2 Important Finding)
## 2026-07-11 Wave 0 Task 1 Important Reviewer-Finding Fix Verification
| 0 | foundation, operations and boundary | Task 1 reviewer-finding fix verified - fresh re-review pending | schema v2, historic baseline 41, 42 active records, reviewer-fix focused tests/Ruff/compileall exit 0 | fresh independent reviewer re-checks the Important identity-validation fix and Task 1 evidence |
| 2026-07-11 | Wave 0 Task 1 - Important reviewer-finding fix | fresh fix implementer | Fresh independent re-review pending | `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py -q` - exit 1, expected blank/whitespace identity tests did not raise | `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q` - exit 0, 18 passed; scoped Ruff and compileall exit 0 | Round-1 Important finding fixed locally; fresh independent re-review pending | `.ai_worklog/task-1-report.md`, `.ai_worklog/task-1-review-1.md` | Approved records now strip both actor IDs, reject blank IDs and reject normalised same-actor identities. No matrix or issue status change. Source SHA-256: models `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`; closure `59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e`; matrix `c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595` |
| Minor | Closure-matrix metadata accepts unsupported programme schema versions and impossible historic-baseline counts | Wave 0 Task 1 foundation | Preserve for broad final-review triage; excluded from the narrowly scoped Important-finding fix |
```
## Review inputs
- Original brief: .ai_worklog/task-1-brief.md
- Implementer/fix report: .ai_worklog/task-1-report.md
- Review rounds: .ai_worklog/task-1-review-1.md and .ai_worklog/task-1-review-2.md
- Earlier package: .ai_worklog/task-1-review-package-rereview.md
