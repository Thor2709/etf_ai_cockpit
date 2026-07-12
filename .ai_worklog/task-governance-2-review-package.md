BASE: 7735afd46b96c4d327754709c8040f98f7bd88fa
HEAD: 09ce88521ac2fd3e09b2893e35ff2247970ea9fc

COMMITS
09ce885 (HEAD -> wave1/governance-task2) feat: split research state and migrate legacy signals

STAT
 .ai_worklog/task-governance-2-brief.md             |  60 ++++  .ai_worklog/task-governance-2-report.md            | 109 +++++++  configs/chatgpt_schema.json                        |  14 +-  .../research_state_migration_report.json           |  31 ++  src/etf_cockpit/chatgpt_bridge/export_pack.py      |  19 +-  src/etf_cockpit/chatgpt_bridge/schemas.py          |  39 +++  src/etf_cockpit/chatgpt_bridge/validation.py       |   6 +-  src/etf_cockpit/core/types.py                      |  62 ++++  src/etf_cockpit/data/score_history.py              | 152 +++++++++-  src/etf_cockpit/governance/migrations.py           | 331 +++++++++++++++++++++  src/etf_cockpit/governance/models.py               |  23 +-  src/etf_cockpit/signals/actions.py                 |  27 ++  src/etf_cockpit/signals/research_states.py         | 266 +++++++++++++++++  src/etf_cockpit/signals/signal_pipeline.py         |  21 +-  src/etf_cockpit/signals/simple_scores.py           |  94 +++++-  tests/test_research_state_migration.py             | 157 ++++++++++  16 files changed, 1385 insertions(+), 26 deletions(-)

DIFF

diff --git a/.ai_worklog/task-governance-2-brief.md b/.ai_worklog/task-governance-2-brief.md
new file mode 100644
index 0000000..e3840e3
--- /dev/null
+++ b/.ai_worklog/task-governance-2-brief.md
@@ -0,0 +1,60 @@
+# Wave 1 Governance Task 2 brief
+
+Read this brief before editing. This is the dependency-ordered Wave 1 Governance Task 2 implementation on branch `wave1/governance-task2`, based on `origin/main` at `7735afd46b96c4d327754709c8040f98f7bd88fa`.
+
+## Required outcome
+
+Split public instrument research state from internal analytical intent and migrate legacy signal/score records from import schema 1.x to governance schema 2.0. The current release must never serialise legacy action verbs as public authority. `execution_allowed` remains the fixed invariant `false`; no broker, order, credential, scoring-weight, model-authority, portfolio-target, research-threshold or coverage change is allowed.
+
+## Binding values
+
+Implement separate enums with exactly these values:
+
+- `ResearchState`: `research_candidate`, `watchlist`, `hold_review`, `avoid`, `needs_evidence`, `manual_review`, `not_scoreable`.
+- `PortfolioReviewState`: `not_applicable`, `maintain_review`, `increase_exposure_review`, `reduce_exposure_review`, `exit_thesis_review`, `constraints_blocked`.
+- `InternalSignalIntent`: `increase`, `maintain`, `decrease`, `exit`, `none` (analytical/backtest namespace only).
+- `GateSeverity`: `blocker`, `authority_warning`, `notice`.
+
+No public state enum may contain `buy`, `sell`, `trade`, `order` or `execute`. Compatibility import code may recognise legacy values but must not export them as current values.
+
+Legacy mapping:
+
+`buy`/`add`/`add_candidate` -> `research_candidate`; `hold`/`trim`/`trim_candidate` -> `hold_review`; `sell` -> `avoid`; `no_trade` -> `needs_evidence`; `manual_review` -> `manual_review`; unknown/missing legacy values -> `manual_review` and never a positive state. Preserve the original value as `legacy_action`. Mark `migration_semantics: lossy` for `trim` and `sell` (and document any consistent safe choice for other converted legacy rows). Portfolio review is `not_applicable` unless a contemporaneous portfolio snapshot is explicitly present.
+
+## Interfaces and files
+
+Create `src/etf_cockpit/signals/research_states.py`, `src/etf_cockpit/governance/migrations.py`, `tests/test_research_state_migration.py`, and `evidence/governance/research_state_migration_report.json`.
+
+Modify `src/etf_cockpit/core/types.py`, `src/etf_cockpit/signals/actions.py`, `src/etf_cockpit/signals/simple_scores.py`, `src/etf_cockpit/data/score_history.py`, and the ChatGPT/export schemas as required. Preserve one-release compatibility for existing internal callers/tests while ensuring v2 release-facing serialisation contains only: `research_state`, `portfolio_review_state`, `analysis_status` (`complete|partial|unavailable`), `research_promotion_allowed`, `portfolio_review_allowed`, `execution_allowed=false`, `legacy_action`, `migration_version`, `gate_policy_version`, `gate_policy_checksum`, `schema_version=2.0`. Existing legacy `action`/`final_action` may be accepted only at compatibility import seams and must not appear in new public v2 exports.
+
+Expose:
+
+```python
+def migrate_legacy_action(record: Mapping[str, object]) -> ResearchStateMigration: ...
+def resolve_research_state(components: Sequence[ScoreComponent], decision: AuthorityDecision) -> ResearchState: ...
+```
+
+Migration must be idempotent and semantically byte-equivalent on repeated application, preserve old records until a validated versioned output exists, and support deterministic checksums/row-count/mapped-unmapped evidence. Add migration/research-state operational events where the existing event interface supports them. Do not implement Task 3's central gate resolver or Task 4's journal/review-report replacement.
+
+## TDD and review contract
+
+Write/run a real RED test before production behaviour, then GREEN and REFACTOR. Required initial command:
+
+```powershell
+.\\.venv\\Scripts\\python.exe -m pytest tests\\test_research_state_migration.py tests\\test_simple_scores.py tests\\test_trade_proposals.py -q
+```
+
+Expected RED is a behavioural failure because the public v2 types/migration do not yet exist, not a syntax/import error. Required GREEN command:
+
+```powershell
+.\\.venv\\Scripts\\python.exe -m pytest tests\\test_research_state_migration.py tests\\test_simple_scores.py tests\\test_score_history.py -q
+```
+
+Also run focused trade-proposal compatibility tests, scoped Ruff, compileall and the full authoritative suite. Record the seven known generated-data/identity failures separately if they reproduce; Task 2 must add no new failures. Produce `.ai_worklog/task-governance-2-report.md` with RED/GREEN/REFACTOR evidence, changed files, migration report checksum, compatibility notes, full results and unresolved gates. Do not close any issue unless its complete issue-level closure dossier passes; this task is a foundation for the Wave 1 governance issue family (`ISSUE-0008`, `ISSUE-0010`, `ISSUE-0030`, `ISSUE-0043`, `ISSUE-0060`, `ISSUE-0066`) and later tasks still own UI, authority, journal and complete closure evidence.
+
+## Global constraints
+
+- Preserve current local-first architecture, revision-protected persistence, atomic I/O, Data Health, provider/evidence contracts, session tracing and audit manifests.
+- `execution_allowed` is always `false`; no authority inflation or execution capability.
+- No invented data, credentials, external uploads, destructive actions or unrelated refactor.
+- Use repository patterns, deterministic tests and explicit unavailable/blocked states.
diff --git a/.ai_worklog/task-governance-2-report.md b/.ai_worklog/task-governance-2-report.md
new file mode 100644
index 0000000..3789947
--- /dev/null
+++ b/.ai_worklog/task-governance-2-report.md
@@ -0,0 +1,109 @@
+# Wave 1 Governance Task 2 implementation report
+
+Status: `DONE_WITH_CONCERNS`
+
+This worktree contains the Task 2 implementation and is not committed. Git
+status/diff commands were unavailable in this Windows worktree because Git's
+helper process could not create its signal pipe; the changed-file list below
+was checked directly from the scoped source/test/evidence paths.
+
+## RED evidence
+
+The required command was first attempted verbatim:
+
+```powershell
+.\\.venv\\Scripts\\python.exe -m pytest tests\\test_research_state_migration.py tests\\test_simple_scores.py tests\\test_trade_proposals.py -q
+```
+
+It exited `1` because this isolated worktree has no local `.venv` and the
+system interpreter has no `pytest` module. Re-running the same command with the
+repository's existing shared environment and this worktree on `PYTHONPATH`
+exited `1` with 11 failures: the five migration-contract assertions (missing
+v2 modules) and the six known generated-data/identity failures in
+`test_simple_scores.py`. No tests were weakened.
+
+After adding the focused behavioural checks for explicit portfolio snapshots,
+v2 signal serialisation and unavailable components, the focused migration RED
+run exited `1` with eight expected failures (missing migration/state modules or
+the not-yet-present `SignalResult.to_v2_dict`).
+
+## GREEN and refactor evidence
+
+Implemented the v2 state/migration seam, then ran:
+
+```powershell
+.\\.venv\\Scripts\\python.exe -m pytest tests\\test_research_state_migration.py tests\\test_simple_scores.py tests\\test_score_history.py -q
+```
+
+Using the shared environment, migration and score-history tests passed; the
+command still exited `1` only for the six pre-existing generated-data/identity
+simple-score failures. The focused trade-proposal compatibility command
+(`tests\\test_trade_proposals.py -q`) exited `0` with 2 passed. Governance policy
+regressions (product, feature, strategy, gate and review tests) exited `0`.
+
+Scoped verification exited `0`:
+
+```powershell
+python -m compileall -q src
+ruff check src/etf_cockpit/signals/research_states.py src/etf_cockpit/governance/migrations.py src/etf_cockpit/governance/models.py src/etf_cockpit/core/types.py src/etf_cockpit/signals/actions.py src/etf_cockpit/signals/signal_pipeline.py src/etf_cockpit/signals/simple_scores.py src/etf_cockpit/data/score_history.py src/etf_cockpit/chatgpt_bridge/schemas.py src/etf_cockpit/chatgpt_bridge/validation.py src/etf_cockpit/chatgpt_bridge/export_pack.py
+```
+
+The authoritative `pytest tests -q` suite exited `1` with seven failures, all
+in the pre-existing generated-data/identity family: the six simple-score
+fixture/coverage rows plus the static trust-artifact identity-count row. No
+Task 2 migration, v2 serialisation, score-history or compatibility test added
+a failure.
+
+## Changed files
+
+- `src/etf_cockpit/signals/research_states.py` - separate public
+  `ResearchState`, `PortfolioReviewState`, `InternalSignalIntent` and
+  `GateSeverity` enums; typed authority/score adapters; fail-closed resolver.
+- `src/etf_cockpit/governance/migrations.py` - deterministic v1.x to v2.0
+  mapping, idempotent `ResearchStateMigration`, explicit snapshot rule,
+  checksums/row-count report helpers and optional operational event.
+- `src/etf_cockpit/core/types.py` - v2 authority fields and serializers on
+  `SignalResult`; legacy `action` remains an import/diagnostic seam.
+- `src/etf_cockpit/signals/actions.py` and `signal_pipeline.py` - internal
+  intent/state adapters and v2 signal-log serialisation.
+- `src/etf_cockpit/signals/simple_scores.py` - v2 authority fields,
+  `to_v2_dict`, and v2 scoreboard frame (legacy `final_action` is opt-in for
+  diagnostics only).
+- `src/etf_cockpit/data/score_history.py` - v2 columns, legacy-row import
+  normalisation, idempotent append and v2 payload helper.
+- `src/etf_cockpit/chatgpt_bridge/schemas.py`, `validation.py` and
+  `export_pack.py` - typed v2 review schema and exports without `action` or
+  `final_action`; v1 imports remain accepted at the compatibility seam.
+- `src/etf_cockpit/governance/models.py` - compatibility aliases to the new
+  enums and authority models.
+- `configs/chatgpt_schema.json` - v2 response/export schema.
+- `tests/test_research_state_migration.py` - focused behavioural coverage.
+- `evidence/governance/research_state_migration_report.json` - deterministic
+  zero-row baseline evidence and checksum.
+
+## Migration evidence and decisions
+
+The report checksum is
+`72ca844a466883cd2bf7e96e588d1239d06c4073ec59152921ad095c50340153`.
+
+Mappings are exact: buy/add/add_candidate to `research_candidate`,
+hold/trim/trim_candidate to `hold_review`, sell to `avoid`, no_trade to
+`needs_evidence`, and manual_review to `manual_review`. Unknown or missing
+values fail closed to `manual_review` while preserving `legacy_action`.
+`trim`, `trim_candidate` and `sell` are marked lossy; the other known mappings
+use the documented conservative lossless marker. `portfolio_review_state`
+stays `not_applicable` unless a contemporaneous snapshot is explicit.
+
+The v2 public field set carries research/portfolio state, analysis status,
+promotion/review flags, `execution_allowed: false`, preserved `legacy_action`,
+migration and gate-policy metadata, and `schema_version: 2.0`. Public serializers
+do not emit `action` or `final_action`; old callers can still read those values
+from in-memory/import/diagnostic seams. All new models force execution false.
+
+## Remaining closure gates
+
+This foundation does not implement the Task 3 central gate resolver or Task 4
+portfolio journal/review-report replacement, and it does not close any issue.
+The seven generated-data/identity failures require their owning fixture/data
+work before a full-suite green claim. Independent review, package/boundary
+verification and later governance UI/journal gates remain outstanding.
diff --git a/configs/chatgpt_schema.json b/configs/chatgpt_schema.json
index ef78798..84c3d4d 100644
--- a/configs/chatgpt_schema.json
+++ b/configs/chatgpt_schema.json
@@ -1,11 +1,21 @@
 {
-  "schema_version": "1.0",
+  "schema_version": "2.0",
   "review_date": "YYYY-MM-DD",
   "overall_view": "risk_on | neutral | risk_off | unclear",
   "portfolio_actions": [
     {
       "etf_id": "string",
-      "action": "hold | no_trade | add_candidate | trim_candidate | manual_review (legacy import compatibility also accepts buy | add | trim | sell)",
+      "research_state": "research_candidate | watchlist | hold_review | avoid | needs_evidence | manual_review | not_scoreable",
+      "portfolio_review_state": "not_applicable | maintain_review | increase_exposure_review | reduce_exposure_review | exit_thesis_review | constraints_blocked",
+      "analysis_status": "complete | partial | unavailable",
+      "research_promotion_allowed": false,
+      "portfolio_review_allowed": false,
+      "execution_allowed": false,
+      "legacy_action": "string or null",
+      "migration_version": "2.0",
+      "gate_policy_version": "string",
+      "gate_policy_checksum": "sha256 or unavailable",
+      "schema_version": "2.0",
       "conviction": 0.0,
       "reason_short": "string",
       "main_supporting_metrics": ["string"],
diff --git a/evidence/governance/research_state_migration_report.json b/evidence/governance/research_state_migration_report.json
new file mode 100644
index 0000000..a33867a
--- /dev/null
+++ b/evidence/governance/research_state_migration_report.json
@@ -0,0 +1,31 @@
+{
+  "legacy_preservation": "Source rows are never mutated; legacy_action is retained in validated v2 rows.",
+  "lossless_values": [
+    "buy",
+    "add",
+    "add_candidate",
+    "hold",
+    "no_trade",
+    "manual_review"
+  ],
+  "lossy_values": [
+    "trim",
+    "trim_candidate",
+    "sell",
+    "unknown",
+    "<missing>"
+  ],
+  "mapped_row_count": 0,
+  "mapped_values": {},
+  "migration_checksum": "72ca844a466883cd2bf7e96e588d1239d06c4073ec59152921ad095c50340153",
+  "migration_version": "2.0",
+  "new_checksum": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
+  "old_checksum": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
+  "portfolio_context_rule": "portfolio_review_state remains not_applicable unless a contemporaneous snapshot is explicit.",
+  "row_count": 0,
+  "schema_version": "2.0",
+  "source_schema_version": "1.x",
+  "target_schema_version": "2.0",
+  "unmapped_row_count": 0,
+  "unmapped_values": []
+}
diff --git a/src/etf_cockpit/chatgpt_bridge/export_pack.py b/src/etf_cockpit/chatgpt_bridge/export_pack.py
index b08ca2c..a36cf97 100644
--- a/src/etf_cockpit/chatgpt_bridge/export_pack.py
+++ b/src/etf_cockpit/chatgpt_bridge/export_pack.py
@@ -53,10 +53,19 @@ GOVERNANCE_CHECKSUMS_PATH = ROOT / "evidence" / "governance" / "policy_checksums
 SIGNAL_TABLE_COLUMNS = [
     "etf_id",
     "name",
-    "action",
+    "research_state",
+    "portfolio_review_state",
+    "analysis_status",
+    "research_promotion_allowed",
+    "portfolio_review_allowed",
+    "execution_allowed",
+    "legacy_action",
+    "migration_version",
+    "gate_policy_version",
+    "gate_policy_checksum",
+    "schema_version",
     "confidence",
     "total_score",
-    "final_action",
     "reason_full",
     "score_1w",
     "score_1m",
@@ -84,14 +93,14 @@ def _signal_rows(signals: Iterable[SignalResult], config: AppConfig) -> list[dic
     names = {etf.id: etf.name for etf in config.universe.etfs}
     rows = []
     for signal in signals:
+        authority = signal.to_v2_dict()
         rows.append(
             {
                 "etf_id": signal.etf_id,
                 "name": names.get(signal.etf_id, signal.etf_id),
-                "action": signal.action,
+                **authority,
                 "confidence": signal.confidence,
                 "total_score": signal.total_score,
-                "final_action": signal.supporting_metrics.get("final_action", signal.action),
                 "reason_full": signal.supporting_metrics.get("reason_full", signal.reason_long),
                 "score_1w": signal.components.momentum,
                 "score_1m": signal.components.trend,
@@ -223,7 +232,7 @@ def export_review_pack(
         "signals": [
             {
                 "etf_id": signal.etf_id,
-                "final_action": signal.action,
+                **signal.to_v2_dict(),
                 "blocked_by": signal.blocked_by,
                 "warnings": signal.warnings,
                 "reason_full": signal.supporting_metrics.get("reason_full", signal.reason_long),
diff --git a/src/etf_cockpit/chatgpt_bridge/schemas.py b/src/etf_cockpit/chatgpt_bridge/schemas.py
index 0d9a801..2ec80c8 100644
--- a/src/etf_cockpit/chatgpt_bridge/schemas.py
+++ b/src/etf_cockpit/chatgpt_bridge/schemas.py
@@ -5,9 +5,12 @@ from typing import Literal
 from pydantic import BaseModel, Field, field_validator

 from etf_cockpit.core.constants import ALLOWED_ACTIONS
+from etf_cockpit.signals.research_states import PortfolioReviewState, ResearchState


 class PortfolioActionAudit(BaseModel):
+    """v1 compatibility import model; never used by v2 exports."""
+
     etf_id: str
     action: Literal["hold", "no_trade", "add_candidate", "trim_candidate", "manual_review", "buy", "add", "trim", "sell"]
     conviction: float = Field(ge=0, le=1)
@@ -18,6 +21,29 @@ class PortfolioActionAudit(BaseModel):
     manual_checks: list[str]


+class PortfolioReviewAudit(BaseModel):
+    """Release-facing v2 review row with no transaction-shaped action field."""
+
+    etf_id: str
+    research_state: ResearchState
+    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
+    analysis_status: Literal["complete", "partial", "unavailable"] = "unavailable"
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    execution_allowed: Literal[False] = False
+    legacy_action: str | None = None
+    migration_version: str = "2.0"
+    gate_policy_version: str = "unavailable"
+    gate_policy_checksum: str = "unavailable"
+    schema_version: Literal["2.0"] = "2.0"
+    conviction: float = Field(default=0.0, ge=0, le=1)
+    reason_short: str = ""
+    main_supporting_metrics: list[str] = Field(default_factory=list)
+    main_risks: list[str] = Field(default_factory=list)
+    blocked_by: list[str] = Field(default_factory=list)
+    manual_checks: list[str] = Field(default_factory=list)
+
+
 class IgnoredSignal(BaseModel):
     etf_id: str
     reason: str
@@ -54,5 +80,18 @@ class ChatGPTAudit(BaseModel):
         return value


+class ChatGPTAuditV2(BaseModel):
+    """Typed v2 external-review import; v1 remains accepted at the seam."""
+
+    schema_version: Literal["2.0"] = "2.0"
+    review_date: str
+    overall_view: Literal["risk_on", "neutral", "risk_off", "unclear"]
+    portfolio_actions: list[PortfolioReviewAudit]
+    ignored_signals: list[IgnoredSignal] = Field(default_factory=list)
+    risk_flags: list[RiskFlag] = Field(default_factory=list)
+    model_audit: ModelAudit
+    dashboard_notes: list[str] = Field(default_factory=list)
+
+
 def allowed_actions() -> tuple[str, ...]:
     return ALLOWED_ACTIONS
diff --git a/src/etf_cockpit/chatgpt_bridge/validation.py b/src/etf_cockpit/chatgpt_bridge/validation.py
index 57a3ed5..5dfa64d 100644
--- a/src/etf_cockpit/chatgpt_bridge/validation.py
+++ b/src/etf_cockpit/chatgpt_bridge/validation.py
@@ -3,7 +3,7 @@ from __future__ import annotations
 import json
 from pathlib import Path

-from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAudit
+from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAudit, ChatGPTAuditV2
 from etf_cockpit.core.exceptions import AuditImportError

 BANNED_EXECUTION_PHRASES = (
@@ -17,7 +17,7 @@ BANNED_EXECUTION_PHRASES = (
 )


-def validate_audit_text(raw_text: str, known_etf_ids: set[str]) -> ChatGPTAudit:
+def validate_audit_text(raw_text: str, known_etf_ids: set[str]) -> ChatGPTAudit | ChatGPTAuditV2:
     lowered = raw_text.lower()
     for phrase in BANNED_EXECUTION_PHRASES:
         if phrase in lowered:
@@ -26,7 +26,7 @@ def validate_audit_text(raw_text: str, known_etf_ids: set[str]) -> ChatGPTAudit:
         payload = json.loads(raw_text)
     except json.JSONDecodeError as exc:
         raise AuditImportError(f"Audit JSON is invalid: {exc}") from exc
-    audit = ChatGPTAudit.model_validate(payload)
+    audit = ChatGPTAuditV2.model_validate(payload) if str(payload.get("schema_version")) == "2.0" else ChatGPTAudit.model_validate(payload)
     referenced_ids = {item.etf_id for item in audit.portfolio_actions} | {item.etf_id for item in audit.ignored_signals}
     unknown = referenced_ids - known_etf_ids
     if unknown:
diff --git a/src/etf_cockpit/core/types.py b/src/etf_cockpit/core/types.py
index d14b6b9..44f4db5 100644
--- a/src/etf_cockpit/core/types.py
+++ b/src/etf_cockpit/core/types.py
@@ -4,6 +4,16 @@ from dataclasses import dataclass, field
 from datetime import date, datetime
 from typing import Literal

+from etf_cockpit.signals.research_states import (
+    AnalysisStatus,
+    InternalSignalIntent,
+    PortfolioReviewState,
+    ResearchState,
+    internal_intent_for_legacy_action,
+    public_authority_payload,
+    research_state_for_legacy_action,
+)
+
 Action = Literal[
     "buy",
     "add",
@@ -113,6 +123,58 @@ class SignalResult:
     status: SignalStatus = "ok"
     model_versions_used: dict[str, str] = field(default_factory=dict)
     timestamp: datetime | None = None
+    # v2 governance fields.  ``action`` remains a one-release compatibility
+    # import/diagnostic seam; release-facing serializers use ``to_v2_dict``.
+    research_state: ResearchState = ResearchState.MANUAL_REVIEW
+    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
+    analysis_status: AnalysisStatus = "unavailable"
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    execution_allowed: Literal[False] = False
+    legacy_action: str | None = None
+    internal_intent: InternalSignalIntent = InternalSignalIntent.NONE
+    migration_version: str = "2.0"
+    gate_policy_version: str = "unavailable"
+    gate_policy_checksum: str = "unavailable"
+    schema_version: str = "2.0"
+
+    def __post_init__(self) -> None:
+        try:
+            object.__setattr__(self, "research_state", ResearchState(str(self.research_state)))
+        except ValueError:
+            object.__setattr__(self, "research_state", ResearchState.MANUAL_REVIEW)
+        try:
+            object.__setattr__(self, "portfolio_review_state", PortfolioReviewState(str(self.portfolio_review_state)))
+        except ValueError:
+            object.__setattr__(self, "portfolio_review_state", PortfolioReviewState.NOT_APPLICABLE)
+        if self.legacy_action is None:
+            object.__setattr__(self, "legacy_action", str(self.action).strip() or None)
+        if self.research_state is ResearchState.MANUAL_REVIEW:
+            object.__setattr__(self, "research_state", research_state_for_legacy_action(self.action))
+        if self.internal_intent is InternalSignalIntent.NONE:
+            object.__setattr__(self, "internal_intent", internal_intent_for_legacy_action(self.action))
+        object.__setattr__(self, "execution_allowed", False)
+        if self.analysis_status == "unavailable":
+            derived: AnalysisStatus = "partial" if self.blocked_by or self.warnings else "complete"
+            object.__setattr__(self, "analysis_status", derived)
+
+    def to_v2_dict(self) -> dict[str, object]:
+        """Return release-facing authority fields without legacy action verbs."""
+
+        return public_authority_payload(
+            research_state=self.research_state,
+            portfolio_review_state=self.portfolio_review_state,
+            analysis_status=self.analysis_status,
+            research_promotion_allowed=self.research_promotion_allowed,
+            portfolio_review_allowed=self.portfolio_review_allowed,
+            legacy_action=self.legacy_action,
+            migration_version=self.migration_version,
+            gate_policy_version=self.gate_policy_version,
+            gate_policy_checksum=self.gate_policy_checksum,
+        )
+
+    def to_public_dict(self) -> dict[str, object]:
+        return self.to_v2_dict()


 @dataclass(frozen=True)
diff --git a/src/etf_cockpit/data/score_history.py b/src/etf_cockpit/data/score_history.py
index fd0a83b..45a20f5 100644
--- a/src/etf_cockpit/data/score_history.py
+++ b/src/etf_cockpit/data/score_history.py
@@ -3,9 +3,16 @@ from __future__ import annotations
 import hashlib
 from dataclasses import dataclass
 from pathlib import Path
+from typing import Literal

 import pandas as pd

+from etf_cockpit.signals.research_states import (
+    PortfolioReviewState,
+    ResearchState,
+    research_state_for_legacy_action,
+)
+

 @dataclass(frozen=True)
 class ScoreHistoryWriteResult:
@@ -13,9 +20,29 @@ class ScoreHistoryWriteResult:
     rows_written: int
     run_id: str
     snapshot_hash: str
+    schema_version: str = "2.0"


-_COLUMNS = ["run_id", "run_completed_at", "instrument_id", "final_combined_score_10", "final_action", "blocked_by", "snapshot_hash"]
+_COLUMNS = [
+    "run_id",
+    "run_completed_at",
+    "instrument_id",
+    "final_combined_score_10",
+    "research_state",
+    "portfolio_review_state",
+    "analysis_status",
+    "research_promotion_allowed",
+    "portfolio_review_allowed",
+    "execution_allowed",
+    "legacy_action",
+    "migration_version",
+    "gate_policy_version",
+    "gate_policy_checksum",
+    "schema_version",
+    "blocked_by",
+    "snapshot_hash",
+]
+LEGACY_COLUMNS = ["run_id", "run_completed_at", "instrument_id", "final_combined_score_10", "final_action", "blocked_by", "snapshot_hash"]


 def append_score_run(scores: pd.DataFrame, run_id: str, created_at: str, *, root: Path) -> ScoreHistoryWriteResult:
@@ -27,17 +54,32 @@ def append_score_run(scores: pd.DataFrame, run_id: str, created_at: str, *, root
     frame = frame.dropna(subset=["instrument_id", "final_combined_score_10"])
     frame["run_id"] = run_id
     frame["run_completed_at"] = created_at
-    for column in ("final_action", "blocked_by"):
-        if column not in frame.columns:
-            frame[column] = ""
+    if "legacy_action" not in frame.columns:
+        frame["legacy_action"] = frame.get("final_action", "")
+    frame["legacy_action"] = frame["legacy_action"].map(lambda value: None if pd.isna(value) else str(value).strip() or None)
+    frame["research_state"] = frame.apply(
+        lambda row: _state_for_row(row), axis=1
+    )
+    frame["portfolio_review_state"] = frame.get("portfolio_review_state", PortfolioReviewState.NOT_APPLICABLE.value)
+    frame["portfolio_review_state"] = frame["portfolio_review_state"].map(_safe_portfolio_state)
+    frame["analysis_status"] = frame.apply(lambda row: _analysis_status_for_row(row), axis=1)
+    frame["research_promotion_allowed"] = False
+    frame["portfolio_review_allowed"] = frame["portfolio_review_state"].ne(PortfolioReviewState.NOT_APPLICABLE.value)
+    frame["execution_allowed"] = False
+    frame["migration_version"] = frame.get("migration_version", "2.0")
+    frame["gate_policy_version"] = frame.get("gate_policy_version", "unavailable")
+    frame["gate_policy_checksum"] = frame.get("gate_policy_checksum", "unavailable")
+    frame["schema_version"] = "2.0"
+    if "blocked_by" not in frame.columns:
+        frame["blocked_by"] = ""
     snapshot_hash = hashlib.sha256(frame.sort_values("instrument_id").to_json().encode()).hexdigest()
     frame["snapshot_hash"] = snapshot_hash
     frame = frame[_COLUMNS]
-    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=_COLUMNS)
+    existing = _normalise_history_frame(pd.read_parquet(path)) if path.exists() else pd.DataFrame(columns=_COLUMNS)
     duplicate = existing[(existing.get("run_id", "") == run_id) & (existing.get("snapshot_hash", "") == snapshot_hash)] if not existing.empty else pd.DataFrame()
     if not duplicate.empty:
         return ScoreHistoryWriteResult(path, 0, run_id, snapshot_hash)
-    combined = pd.concat([existing, frame], ignore_index=True).drop_duplicates(subset=["run_id", "instrument_id"], keep="last")
+    combined = pd.concat([existing, frame], ignore_index=True).reindex(columns=_COLUMNS).drop_duplicates(subset=["run_id", "instrument_id"], keep="last")
     path.parent.mkdir(parents=True, exist_ok=True)
     combined.to_parquet(path, index=False)
     return ScoreHistoryWriteResult(path, len(frame), run_id, snapshot_hash)
@@ -48,7 +90,101 @@ def score_history_frame(*, root: Path) -> pd.DataFrame:
     if not path.exists():
         return pd.DataFrame(columns=_COLUMNS)
     try:
-        frame = pd.read_parquet(path)
+        frame = _normalise_history_frame(pd.read_parquet(path))
     except Exception:
         return pd.DataFrame(columns=_COLUMNS)
-    return frame.reindex(columns=[column for column in _COLUMNS if column in frame.columns]).copy()
+    return frame.reindex(columns=_COLUMNS).copy()
+
+
+def score_history_v2_payload(row: object) -> dict[str, object]:
+    """Serialise a score/history row without ``action`` or ``final_action``."""
+
+    if isinstance(row, pd.Series):
+        values = row.to_dict()
+    elif isinstance(row, dict):
+        values = dict(row)
+    else:
+        values = {column: getattr(row, column, None) for column in _COLUMNS}
+    legacy = values.get("legacy_action", values.get("final_action"))
+    state = values.get("research_state") or research_state_for_legacy_action(legacy).value
+    portfolio_state = values.get("portfolio_review_state") or PortfolioReviewState.NOT_APPLICABLE.value
+    return {
+        "research_state": ResearchState(str(state)).value if str(state) in {item.value for item in ResearchState} else ResearchState.MANUAL_REVIEW.value,
+        "portfolio_review_state": _safe_portfolio_state(portfolio_state),
+        "analysis_status": _analysis_status_for_row(values),
+        "research_promotion_allowed": False,
+        "portfolio_review_allowed": _safe_portfolio_state(portfolio_state) != PortfolioReviewState.NOT_APPLICABLE.value,
+        "execution_allowed": False,
+        "legacy_action": None if legacy is None or (isinstance(legacy, float) and pd.isna(legacy)) else str(legacy).strip() or None,
+        "migration_version": str(values.get("migration_version") or "2.0"),
+        "gate_policy_version": str(values.get("gate_policy_version") or "unavailable"),
+        "gate_policy_checksum": str(values.get("gate_policy_checksum") or "unavailable"),
+        "schema_version": "2.0",
+    }
+
+
+def append_score_run_v2(scores: pd.DataFrame, run_id: str, created_at: str, *, root: Path) -> ScoreHistoryWriteResult:
+    """Explicit v2 name for callers migrating away from the legacy API."""
+
+    return append_score_run(scores, run_id, created_at, root=root)
+
+
+def _state_for_row(row: object) -> str:
+    values = row.to_dict() if isinstance(row, pd.Series) else row
+    if isinstance(values, dict) and values.get("research_state"):
+        try:
+            return ResearchState(str(values["research_state"])).value
+        except ValueError:
+            pass
+    legacy = values.get("legacy_action") if isinstance(values, dict) else None
+    if legacy is None and isinstance(values, dict):
+        legacy = values.get("final_action")
+    return research_state_for_legacy_action(legacy).value
+
+
+def _safe_portfolio_state(value: object) -> str:
+    try:
+        return PortfolioReviewState(str(value)).value
+    except ValueError:
+        return PortfolioReviewState.NOT_APPLICABLE.value
+
+
+def _analysis_status_for_row(row: object) -> Literal["complete", "partial", "unavailable"]:
+    values = row.to_dict() if isinstance(row, pd.Series) else row
+    candidate = values.get("analysis_status") if isinstance(values, dict) else None
+    if str(candidate or "").casefold() in {"complete", "partial", "unavailable"}:
+        return str(candidate).casefold()  # type: ignore[return-value]
+    if isinstance(values, dict) and values.get("research_state"):
+        return "partial"
+    return "partial" if isinstance(values, dict) and values.get("legacy_action", values.get("final_action")) else "unavailable"
+
+
+def _normalise_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
+    if frame.empty:
+        return pd.DataFrame(columns=_COLUMNS)
+    result = frame.copy()
+    if "legacy_action" not in result.columns:
+        result["legacy_action"] = result.get("final_action", None)
+    if "research_state" not in result.columns:
+        result["research_state"] = result.apply(_state_for_row, axis=1)
+    else:
+        result["research_state"] = result["research_state"].map(lambda value: _state_for_row({"research_state": value}))
+    if "portfolio_review_state" not in result.columns:
+        result["portfolio_review_state"] = PortfolioReviewState.NOT_APPLICABLE.value
+    result["portfolio_review_state"] = result["portfolio_review_state"].map(_safe_portfolio_state)
+    if "analysis_status" not in result.columns:
+        result["analysis_status"] = result.apply(_analysis_status_for_row, axis=1)
+    result["research_promotion_allowed"] = False
+    result["portfolio_review_allowed"] = result["portfolio_review_state"].ne(PortfolioReviewState.NOT_APPLICABLE.value)
+    result["execution_allowed"] = False
+    for column, default in (
+        ("migration_version", "2.0"),
+        ("gate_policy_version", "unavailable"),
+        ("gate_policy_checksum", "unavailable"),
+        ("schema_version", "2.0"),
+        ("blocked_by", ""),
+        ("snapshot_hash", ""),
+    ):
+        if column not in result.columns:
+            result[column] = default
+    return result.reindex(columns=_COLUMNS)
diff --git a/src/etf_cockpit/governance/migrations.py b/src/etf_cockpit/governance/migrations.py
new file mode 100644
index 0000000..7ce336d
--- /dev/null
+++ b/src/etf_cockpit/governance/migrations.py
@@ -0,0 +1,331 @@
+"""Deterministic v1.x signal/action to governance schema 2.0 migration.
+
+The migration is intentionally a pure adapter.  It never mutates a supplied
+record and does not replace a source catalogue.  Callers can validate the
+returned versioned rows before publishing a pointer or writing an export.
+"""
+
+from __future__ import annotations
+
+import hashlib
+import json
+from collections import Counter
+from pathlib import Path
+from typing import Any, Iterable, Literal, Mapping
+
+import yaml
+from pydantic import BaseModel, ConfigDict, Field
+
+from etf_cockpit.core.paths import CONFIG_DIR
+from etf_cockpit.signals.research_states import (
+    AnalysisStatus,
+    PortfolioReviewState,
+    ResearchState,
+    research_state_for_legacy_action,
+)
+
+
+V1_SCHEMA_PREFIXES = ("1", "1.")
+V2_SCHEMA_VERSION = "2.0"
+MIGRATION_VERSION = "2.0"
+GATE_POLICY_PATH = CONFIG_DIR / "gate_policy.yaml"
+
+
+class ResearchStateMigration(BaseModel):
+    """Canonical v2 row returned by :func:`migrate_legacy_action`."""
+
+    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
+
+    research_state: ResearchState
+    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
+    analysis_status: AnalysisStatus = "unavailable"
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    execution_allowed: Literal[False] = Field(default=False, frozen=True)
+    legacy_action: str | None = None
+    migration_semantics: str = "lossy"
+    migration_version: str = MIGRATION_VERSION
+    gate_policy_version: str = "unavailable"
+    gate_policy_checksum: str = "unavailable"
+    schema_version: str = V2_SCHEMA_VERSION
+
+    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
+        """Default to JSON-compatible enum values for stable idempotency."""
+
+        kwargs.setdefault("mode", "json")
+        return super().model_dump(*args, **kwargs)
+
+    def to_v2_dict(self) -> dict[str, Any]:
+        return self.model_dump(mode="json")
+
+    def to_public_dict(self) -> dict[str, Any]:
+        return self.to_v2_dict()
+
+
+def _canonical_json(value: object) -> str:
+    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
+
+
+def _sha256(value: object) -> str:
+    payload = value if isinstance(value, bytes) else _canonical_json(value).encode("utf-8")
+    return hashlib.sha256(payload).hexdigest()
+
+
+def _gate_policy_metadata() -> tuple[str, str]:
+    """Read only deterministic gate metadata; unavailable is fail-closed."""
+
+    try:
+        raw = GATE_POLICY_PATH.read_bytes()
+        payload = yaml.safe_load(raw.decode("utf-8"))
+        version = str(payload.get("policy_version") or payload.get("schema_version") or "unavailable") if isinstance(payload, Mapping) else "unavailable"
+        return version, hashlib.sha256(raw).hexdigest()
+    except (OSError, UnicodeError, yaml.YAMLError):
+        return "unavailable", "unavailable"
+
+
+def _valid_analysis_status(value: object, *, fallback: AnalysisStatus) -> AnalysisStatus:
+    text = str(value or "").strip().casefold()
+    return text if text in {"complete", "partial", "unavailable"} else fallback  # type: ignore[return-value]
+
+
+def _snapshot_mapping(record: Mapping[str, object]) -> Mapping[str, object] | None:
+    """Return an explicitly contemporaneous portfolio snapshot, if present."""
+
+    for key in ("portfolio_snapshot", "portfolio_context", "holdings_snapshot"):
+        candidate = record.get(key)
+        if not isinstance(candidate, Mapping):
+            continue
+        # A free-form ``portfolio: {notes: ...}`` block is not snapshot
+        # evidence.  Require a timestamp/date, holdings/weights, or an
+        # explicit review state to avoid inferring portfolio authority.
+        markers = {
+            "as_of_date",
+            "as_of",
+            "snapshot_at",
+            "timestamp",
+            "holdings",
+            "positions",
+            "current_weight",
+            "target_weight",
+            "portfolio_review_state",
+            "review_state",
+        }
+        if markers.intersection(str(item) for item in candidate):
+            return candidate
+    return None
+
+
+def _portfolio_state(record: Mapping[str, object]) -> tuple[PortfolioReviewState, bool]:
+    snapshot = _snapshot_mapping(record)
+    if snapshot is None:
+        return PortfolioReviewState.NOT_APPLICABLE, False
+
+    raw_state = snapshot.get("portfolio_review_state", snapshot.get("review_state", snapshot.get("state")))
+    if raw_state is not None:
+        text = str(raw_state).strip().casefold()
+        try:
+            return PortfolioReviewState(text), text != PortfolioReviewState.NOT_APPLICABLE.value
+        except ValueError:
+            # Legacy portfolio verbs are context only; use a safe review row.
+            if text in {"buy", "add", "add_candidate", "increase", "increase_exposure"}:
+                return PortfolioReviewState.INCREASE_EXPOSURE_REVIEW, True
+            if text in {"trim", "trim_candidate", "decrease", "reduce", "reduce_exposure"}:
+                return PortfolioReviewState.REDUCE_EXPOSURE_REVIEW, True
+            if text in {"sell", "exit", "close"}:
+                return PortfolioReviewState.EXIT_THESIS_REVIEW, True
+            if text in {"hold", "maintain", "no_trade"}:
+                return PortfolioReviewState.MAINTAIN_REVIEW, True
+            return PortfolioReviewState.CONSTRAINTS_BLOCKED, True
+    return PortfolioReviewState.MAINTAIN_REVIEW, True
+
+
+def _legacy_text(record: Mapping[str, object]) -> str | None:
+    value = record.get("legacy_action") if "legacy_action" in record else record.get("action", record.get("final_action"))
+    if value is None:
+        return None
+    text = str(value).strip()
+    return text or None
+
+
+def _already_v2(record: Mapping[str, object]) -> bool:
+    return str(record.get("schema_version") or "").strip() == V2_SCHEMA_VERSION and "research_state" in record
+
+
+def migrate_legacy_action(record: Mapping[str, object]) -> ResearchStateMigration:
+    """Map one v1.x row to a canonical v2 governance row.
+
+    Unknown/missing actions are explicitly mapped to ``manual_review``.  A v2
+    row is normalised again rather than returned by reference, making repeated
+    migration semantically and byte-equivalent.
+    """
+
+    if not isinstance(record, Mapping):
+        raise TypeError("legacy record must be a mapping")
+
+    gate_version, gate_checksum = _gate_policy_metadata()
+    if _already_v2(record):
+        raw_state = record.get("research_state")
+        try:
+            state = ResearchState(str(raw_state))
+        except ValueError:
+            state = ResearchState.MANUAL_REVIEW
+        portfolio_state, context_allowed = _portfolio_state(record)
+        try:
+            portfolio_state = PortfolioReviewState(str(record.get("portfolio_review_state") or portfolio_state.value))
+        except ValueError:
+            portfolio_state = PortfolioReviewState.NOT_APPLICABLE
+        analysis_status = _valid_analysis_status(record.get("analysis_status"), fallback="unavailable")
+        legacy_action = _legacy_text(record)
+        semantics = str(record.get("migration_semantics") or "lossy").strip().casefold()
+        if semantics not in {"lossless", "lossy"}:
+            semantics = "lossy"
+        return ResearchStateMigration(
+            research_state=state,
+            portfolio_review_state=portfolio_state,
+            analysis_status=analysis_status,
+            research_promotion_allowed=bool(record.get("research_promotion_allowed", False)) and state is not ResearchState.MANUAL_REVIEW,
+            portfolio_review_allowed=bool(record.get("portfolio_review_allowed", context_allowed)) and context_allowed,
+            execution_allowed=False,
+            legacy_action=legacy_action,
+            migration_semantics=semantics,
+            migration_version=str(record.get("migration_version") or MIGRATION_VERSION),
+            gate_policy_version=str(record.get("gate_policy_version") or gate_version),
+            gate_policy_checksum=str(record.get("gate_policy_checksum") or gate_checksum),
+            schema_version=V2_SCHEMA_VERSION,
+        )
+
+    legacy_action = _legacy_text(record)
+    state = research_state_for_legacy_action(legacy_action)
+    action_key = legacy_action.casefold() if legacy_action is not None else ""
+    # Transactional decrease/exit intent cannot be reconstructed as a public
+    # action; those rows are explicitly marked lossy.  Unknown/missing rows
+    # also retain a lossy marker because no positive interpretation is safe.
+    semantics = "lossy" if action_key in {"trim", "trim_candidate", "sell", "", "unknown"} else "lossless"
+    portfolio_state, portfolio_allowed = _portfolio_state(record)
+    status_fallback: AnalysisStatus = "partial" if legacy_action is not None and action_key in {
+        "buy",
+        "add",
+        "add_candidate",
+        "hold",
+        "trim",
+        "trim_candidate",
+        "sell",
+        "no_trade",
+        "manual_review",
+    } else "unavailable"
+    analysis_status = _valid_analysis_status(record.get("analysis_status"), fallback=status_fallback)
+    # Promotion remains false until the policy-driven resolver (Task 3) has
+    # checked the complete evidence/gate set.
+    return ResearchStateMigration(
+        research_state=state,
+        portfolio_review_state=portfolio_state,
+        analysis_status=analysis_status,
+        research_promotion_allowed=False,
+        portfolio_review_allowed=portfolio_allowed,
+        execution_allowed=False,
+        legacy_action=legacy_action,
+        migration_semantics=semantics,
+        migration_version=MIGRATION_VERSION,
+        gate_policy_version=str(record.get("gate_policy_version") or gate_version),
+        gate_policy_checksum=str(record.get("gate_policy_checksum") or gate_checksum),
+        schema_version=V2_SCHEMA_VERSION,
+    )
+
+
+def migrate_records(records: Iterable[Mapping[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
+    """Migrate rows and return canonical rows plus deterministic evidence."""
+
+    source_rows = [dict(record) for record in records]
+    migrated = [migrate_legacy_action(record).to_v2_dict() for record in source_rows]
+    actions = [_legacy_text(record) for record in source_rows]
+    known = Counter(action.casefold() for action in actions if action and action.casefold() in {
+        "buy",
+        "add",
+        "add_candidate",
+        "hold",
+        "trim",
+        "trim_candidate",
+        "sell",
+        "no_trade",
+        "manual_review",
+    })
+    unknown = sorted({action for action in (action.casefold() if action else "<missing>" for action in actions) if action not in known})
+    report: dict[str, object] = {
+        "schema_version": V2_SCHEMA_VERSION,
+        "migration_version": MIGRATION_VERSION,
+        "source_schema_version": "1.x",
+        "target_schema_version": V2_SCHEMA_VERSION,
+        "row_count": len(source_rows),
+        "mapped_row_count": sum(known.values()),
+        "unmapped_row_count": len(source_rows) - sum(known.values()),
+        "mapped_values": dict(sorted(known.items())),
+        "unmapped_values": unknown,
+        "old_checksum": _sha256(source_rows),
+        "new_checksum": _sha256(migrated),
+        "legacy_preservation": "Source rows are never mutated; legacy_action is retained in validated v2 rows.",
+        "portfolio_context_rule": "portfolio_review_state remains not_applicable unless a contemporaneous snapshot is explicit.",
+        "lossy_values": ["trim", "trim_candidate", "sell", "unknown", "<missing>"],
+        "lossless_values": [
+            "buy",
+            "add",
+            "add_candidate",
+            "hold",
+            "no_trade",
+            "manual_review",
+        ],
+    }
+    report["migration_checksum"] = _sha256(report)
+    return migrated, report
+
+
+def write_migration_report(
+    records: Iterable[Mapping[str, object]],
+    path: Path,
+) -> dict[str, object]:
+    """Write deterministic migration evidence without deleting source rows."""
+
+    _, report = migrate_records(records)
+    destination = Path(path)
+    destination.parent.mkdir(parents=True, exist_ok=True)
+    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
+    return report
+
+
+def log_migration_event(report: Mapping[str, object], *, path: Path | None = None) -> None:
+    """Record a redacted operational migration event on the existing trace."""
+
+    try:
+        from etf_cockpit.core.session_log import log_event
+
+        log_event(
+            event_type="research_state_migration",
+            component="governance.migrations",
+            operation="migrate_v1_to_v2",
+            status="complete",
+            row_counts={
+                "rows": int(report.get("row_count", 0)),
+                "mapped": int(report.get("mapped_row_count", 0)),
+                "unmapped": int(report.get("unmapped_row_count", 0)),
+            },
+            checksums={
+                key: str(report[key])
+                for key in ("old_checksum", "new_checksum", "migration_checksum")
+                if report.get(key)
+            },
+            path=path,
+        )
+    except Exception:
+        # Migration evidence must never be blocked by an unavailable log.
+        return
+
+
+__all__ = [
+    "GATE_POLICY_PATH",
+    "MIGRATION_VERSION",
+    "ResearchStateMigration",
+    "V2_SCHEMA_VERSION",
+    "migrate_legacy_action",
+    "migrate_records",
+    "log_migration_event",
+    "write_migration_report",
+]
diff --git a/src/etf_cockpit/governance/models.py b/src/etf_cockpit/governance/models.py
index e385a0d..483969a 100644
--- a/src/etf_cockpit/governance/models.py
+++ b/src/etf_cockpit/governance/models.py
@@ -12,6 +12,16 @@ from typing import Generic, Literal, TypeVar

 from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

+from etf_cockpit.signals.research_states import (
+    AuthorityDecision,
+    GateResult,
+    GateSeverity as GateSeverityEnum,
+    InternalSignalIntent,
+    PortfolioReviewState,
+    ResearchState as PublicResearchState,
+    ScoreComponent,
+)
+

 SCHEMA_VERSION = "1.0"
 SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})
@@ -32,8 +42,10 @@ Authority = Literal[
     "user_record",
     "none",
 ]
-ResearchState = Literal["research_candidate", "manual_review", "not_scoreable"]
-GateSeverity = Literal["blocker", "authority_warning", "notice"]
+# Compatibility aliases for Task 1 policy callers.  The public values now
+# come from the dedicated v2 state module and remain string-compatible.
+ResearchState = PublicResearchState
+GateSeverity = GateSeverityEnum

 # These are the policy terms and gate identifiers required by GOV-01.4-GOV-01.7.
 # Keeping the lists in the typed contract makes completeness checks deterministic
@@ -423,6 +435,13 @@ __all__ = [
     "GovernanceLoadResult",
     "ImmutableModel",
     "Authority",
+    "AuthorityDecision",
+    "GateResult",
+    "GateSeverity",
+    "InternalSignalIntent",
+    "PortfolioReviewState",
+    "ResearchState",
+    "ScoreComponent",
     "ProductDefinition",
     "PolicyModel",
     "ProductGovernancePolicy",
diff --git a/src/etf_cockpit/signals/actions.py b/src/etf_cockpit/signals/actions.py
index 188a03d..c4735b5 100644
--- a/src/etf_cockpit/signals/actions.py
+++ b/src/etf_cockpit/signals/actions.py
@@ -2,6 +2,12 @@ from __future__ import annotations

 from etf_cockpit.core.config import AppConfig
 from etf_cockpit.core.types import Action
+from etf_cockpit.signals.research_states import (
+    InternalSignalIntent,
+    ResearchState,
+    internal_intent_for_legacy_action,
+    research_state_for_legacy_action,
+)


 def preliminary_action(
@@ -57,3 +63,24 @@ def advisory_action(action: Action) -> Action:
     if action in {"trim", "sell"}:
         return "trim_candidate"
     return action
+
+
+def internal_signal_intent(action: object) -> InternalSignalIntent:
+    """Compatibility adapter from v1 action text to analytical intent."""
+
+    return internal_intent_for_legacy_action(action)
+
+
+def public_research_state(action: object) -> ResearchState:
+    """Compatibility adapter that fails closed on unknown action text."""
+
+    return research_state_for_legacy_action(action)
+
+
+__all__ = [
+    "advisory_action",
+    "apply_gate_result",
+    "internal_signal_intent",
+    "preliminary_action",
+    "public_research_state",
+]
diff --git a/src/etf_cockpit/signals/research_states.py b/src/etf_cockpit/signals/research_states.py
new file mode 100644
index 0000000..7a01340
--- /dev/null
+++ b/src/etf_cockpit/signals/research_states.py
@@ -0,0 +1,266 @@
+"""Typed public research state and internal analytical-intent contracts.
+
+The historical signal pipeline still has callers that pass the v1 ``action``
+strings.  Those strings are deliberately kept at compatibility boundaries;
+the models and helpers in this module are the release-facing vocabulary.  A
+state never implies an executable order and every public authority contract
+keeps ``execution_allowed`` fixed to ``False``.
+"""
+
+from __future__ import annotations
+
+from dataclasses import dataclass
+from enum import StrEnum
+from typing import Literal, Mapping, Sequence
+
+from pydantic import BaseModel, ConfigDict, Field
+
+
+class ResearchState(StrEnum):
+    """Public, instrument-level research lifecycle state."""
+
+    RESEARCH_CANDIDATE = "research_candidate"
+    WATCHLIST = "watchlist"
+    HOLD_REVIEW = "hold_review"
+    AVOID = "avoid"
+    NEEDS_EVIDENCE = "needs_evidence"
+    MANUAL_REVIEW = "manual_review"
+    NOT_SCOREABLE = "not_scoreable"
+
+
+class PortfolioReviewState(StrEnum):
+    """Portfolio context is separate from instrument research state."""
+
+    NOT_APPLICABLE = "not_applicable"
+    MAINTAIN_REVIEW = "maintain_review"
+    INCREASE_EXPOSURE_REVIEW = "increase_exposure_review"
+    REDUCE_EXPOSURE_REVIEW = "reduce_exposure_review"
+    EXIT_THESIS_REVIEW = "exit_thesis_review"
+    CONSTRAINTS_BLOCKED = "constraints_blocked"
+
+
+class InternalSignalIntent(StrEnum):
+    """Analytical/backtest intent; never a public authority state."""
+
+    INCREASE = "increase"
+    MAINTAIN = "maintain"
+    DECREASE = "decrease"
+    EXIT = "exit"
+    NONE = "none"
+
+
+class GateSeverity(StrEnum):
+    BLOCKER = "blocker"
+    AUTHORITY_WARNING = "authority_warning"
+    NOTICE = "notice"
+
+
+AnalysisStatus = Literal["complete", "partial", "unavailable"]
+MigrationSemantics = Literal["lossless", "lossy"]
+
+
+@dataclass(frozen=True)
+class ScoreComponent:
+    """Small adapter accepted by :func:`resolve_research_state`.
+
+    Existing ``SimpleScoreComponent`` instances are intentionally accepted by
+    duck typing, so this type is useful for focused governance tests without
+    coupling the governance module to the scoring implementation.
+    """
+
+    key: str
+    status: str = "ok"
+    score: float | None = None
+    authority: str = "evidence"
+    source_id: str | None = None
+
+
+class GateResult(BaseModel):
+    """Typed gate evidence used by the migration/research-state adapter."""
+
+    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
+
+    gate_id: str = Field(min_length=1)
+    severity: GateSeverity = GateSeverity.NOTICE
+    passed: bool = True
+    message: str = ""
+
+
+class AuthorityDecision(BaseModel):
+    """A conservative decision envelope consumed by state adapters.
+
+    Task 3 owns the central gate resolver.  Task 2 only needs a typed seam, so
+    defaults intentionally remain diagnostic and non-promoting.
+    """
+
+    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
+
+    analysis_status: AnalysisStatus = "unavailable"
+    research_state: ResearchState = ResearchState.MANUAL_REVIEW
+    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    execution_allowed: Literal[False] = False
+    gates: tuple[GateResult, ...] = ()
+
+
+# Compatibility import values are deliberately kept out of all public enums.
+LEGACY_ACTION_TO_RESEARCH_STATE: Mapping[str, ResearchState] = {
+    "buy": ResearchState.RESEARCH_CANDIDATE,
+    "add": ResearchState.RESEARCH_CANDIDATE,
+    "add_candidate": ResearchState.RESEARCH_CANDIDATE,
+    "hold": ResearchState.HOLD_REVIEW,
+    "trim": ResearchState.HOLD_REVIEW,
+    "trim_candidate": ResearchState.HOLD_REVIEW,
+    "sell": ResearchState.AVOID,
+    "no_trade": ResearchState.NEEDS_EVIDENCE,
+    "manual_review": ResearchState.MANUAL_REVIEW,
+}
+
+LEGACY_ACTION_TO_INTENT: Mapping[str, InternalSignalIntent] = {
+    "buy": InternalSignalIntent.INCREASE,
+    "add": InternalSignalIntent.INCREASE,
+    "add_candidate": InternalSignalIntent.INCREASE,
+    "hold": InternalSignalIntent.MAINTAIN,
+    "trim": InternalSignalIntent.DECREASE,
+    "trim_candidate": InternalSignalIntent.DECREASE,
+    "sell": InternalSignalIntent.EXIT,
+    "no_trade": InternalSignalIntent.NONE,
+    "manual_review": InternalSignalIntent.NONE,
+}
+
+
+def normalise_legacy_action(value: object) -> str | None:
+    """Return a stable text representation while preserving missing values."""
+
+    if value is None:
+        return None
+    text = str(value).strip()
+    return text or None
+
+
+def research_state_for_legacy_action(value: object) -> ResearchState:
+    """Map a v1 action to a safe public state, failing closed on unknown text."""
+
+    action = normalise_legacy_action(value)
+    return LEGACY_ACTION_TO_RESEARCH_STATE.get(
+        action.casefold() if action is not None else "",
+        ResearchState.MANUAL_REVIEW,
+    )
+
+
+def internal_intent_for_legacy_action(value: object) -> InternalSignalIntent:
+    action = normalise_legacy_action(value)
+    return LEGACY_ACTION_TO_INTENT.get(
+        action.casefold() if action is not None else "",
+        InternalSignalIntent.NONE,
+    )
+
+
+def _component_status(component: object) -> str:
+    return str(getattr(component, "status", "") or "").strip().casefold()
+
+
+def _component_score(component: object) -> float | None:
+    value = getattr(component, "score", None)
+    if value is None:
+        value = getattr(component, "score_10", None)
+    try:
+        return None if value is None else float(value)
+    except (TypeError, ValueError):
+        return None
+
+
+def resolve_research_state(
+    components: Sequence[ScoreComponent | object],
+    decision: AuthorityDecision,
+) -> ResearchState:
+    """Resolve a public state without allowing unavailable evidence to promote it.
+
+    This is deliberately a narrow adapter, not Task 3's gate resolver.  The
+    decision's already-resolved non-positive state is retained; a positive
+    candidate requires complete analysis and at least one usable non-model
+    component.  Blockers or malformed evidence always fail closed.
+    """
+
+    try:
+        typed_decision = decision if isinstance(decision, AuthorityDecision) else AuthorityDecision.model_validate(decision)
+    except Exception:
+        return ResearchState.MANUAL_REVIEW
+
+    states = {item.value for item in ResearchState}
+    if typed_decision.research_state.value not in states:
+        return ResearchState.MANUAL_REVIEW
+
+    if typed_decision.analysis_status == "unavailable":
+        return ResearchState.NOT_SCOREABLE
+
+    if any(
+        _component_status(component)
+        in {"blocked", "blocker", "failed", "unavailable", "invalid", "n/a", "na"}
+        for component in components
+    ):
+        return ResearchState.NOT_SCOREABLE
+
+    usable = [
+        component
+        for component in components
+        if _component_score(component) is not None
+        and str(getattr(component, "source_id", "") or "").split(":", 1)[0].casefold() != "model"
+    ]
+    if typed_decision.research_state is ResearchState.RESEARCH_CANDIDATE and not usable:
+        return ResearchState.NOT_SCOREABLE
+
+    # An authority warning may downgrade positive promotion but does not need
+    # to invent a new state.  The central resolver in Task 3 owns that policy.
+    return typed_decision.research_state
+
+
+def public_authority_payload(
+    *,
+    research_state: ResearchState | str,
+    portfolio_review_state: PortfolioReviewState | str = PortfolioReviewState.NOT_APPLICABLE,
+    analysis_status: AnalysisStatus = "unavailable",
+    research_promotion_allowed: bool = False,
+    portfolio_review_allowed: bool = False,
+    legacy_action: object = None,
+    migration_version: str = "2.0",
+    gate_policy_version: str = "unavailable",
+    gate_policy_checksum: str = "unavailable",
+) -> dict[str, object]:
+    """Build the release-facing v2 authority fields in deterministic order."""
+
+    state = ResearchState(research_state)
+    portfolio_state = PortfolioReviewState(portfolio_review_state)
+    return {
+        "research_state": state.value,
+        "portfolio_review_state": portfolio_state.value,
+        "analysis_status": analysis_status,
+        "research_promotion_allowed": bool(research_promotion_allowed),
+        "portfolio_review_allowed": bool(portfolio_review_allowed),
+        "execution_allowed": False,
+        "legacy_action": normalise_legacy_action(legacy_action),
+        "migration_version": str(migration_version),
+        "gate_policy_version": str(gate_policy_version),
+        "gate_policy_checksum": str(gate_policy_checksum),
+        "schema_version": "2.0",
+    }
+
+
+__all__ = [
+    "AnalysisStatus",
+    "AuthorityDecision",
+    "GateResult",
+    "GateSeverity",
+    "InternalSignalIntent",
+    "LEGACY_ACTION_TO_INTENT",
+    "LEGACY_ACTION_TO_RESEARCH_STATE",
+    "PortfolioReviewState",
+    "ResearchState",
+    "ScoreComponent",
+    "internal_intent_for_legacy_action",
+    "normalise_legacy_action",
+    "public_authority_payload",
+    "research_state_for_legacy_action",
+    "resolve_research_state",
+]
diff --git a/src/etf_cockpit/signals/signal_pipeline.py b/src/etf_cockpit/signals/signal_pipeline.py
index 4fb2715..9336529 100644
--- a/src/etf_cockpit/signals/signal_pipeline.py
+++ b/src/etf_cockpit/signals/signal_pipeline.py
@@ -1,6 +1,5 @@
 from __future__ import annotations

-from dataclasses import asdict
 from datetime import date, datetime, timezone

 import pandas as pd
@@ -175,8 +174,24 @@ def generate_signals(


 def _signal_to_json(signal: SignalResult) -> dict[str, object]:
-    data = asdict(signal)
-    data["timestamp"] = signal.timestamp.isoformat() if signal.timestamp else None
+    # Operational signal traces use the v2 authority seam.  The legacy
+    # ``action``/``final_action`` values remain available on the in-memory
+    # object for compatibility callers but are not published here.
+    data = signal.to_v2_dict()
+    data.update(
+        {
+            "run_id": signal.run_id,
+            "signal_date": signal.signal_date.isoformat(),
+            "etf_id": signal.etf_id,
+            "confidence": signal.confidence,
+            "total_score": signal.total_score,
+            "blocked_by": signal.blocked_by,
+            "warnings": signal.warnings,
+            "reason_short": signal.reason_short,
+            "reason_long": signal.reason_long,
+            "timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
+        }
+    )
     return data


diff --git a/src/etf_cockpit/signals/simple_scores.py b/src/etf_cockpit/signals/simple_scores.py
index 29aeba8..a526302 100644
--- a/src/etf_cockpit/signals/simple_scores.py
+++ b/src/etf_cockpit/signals/simple_scores.py
@@ -4,7 +4,7 @@ from dataclasses import dataclass
 from datetime import date
 from math import isfinite, tanh
 from pathlib import Path
-from typing import Iterable
+from typing import Iterable, Literal

 import pandas as pd

@@ -17,6 +17,15 @@ from etf_cockpit.data.yfinance_provider import yfinance_symbol_map_from_config
 from etf_cockpit.features.regime import build_benchmark_attribution_lookup, build_market_regime, build_portfolio_fit_lookup
 from etf_cockpit.models.calibration import calibration_lookup, evaluate_forecast_calibration, load_forecast_history
 from etf_cockpit.models.forecast_scores import forecast_component_maps, forecast_score_details, load_latest_forecasts
+from etf_cockpit.signals.research_states import (
+    AnalysisStatus,
+    InternalSignalIntent,
+    PortfolioReviewState,
+    ResearchState,
+    internal_intent_for_legacy_action,
+    public_authority_payload,
+    research_state_for_legacy_action,
+)
 from etf_cockpit.signals.strategy_templates import strategy_template_frame, strategy_template_labels, template_description


@@ -208,6 +217,63 @@ class SimpleInstrumentScore:
     net_expected_edge_bps: float | None = None
     edge_to_cost_ratio: float | None = None
     cost_stress_scenario: str = "not_evaluated"
+    # v2 public authority fields.  ``final_action`` is retained solely as an
+    # internal compatibility seam and is omitted by ``to_v2_dict``.
+    research_state: ResearchState = ResearchState.MANUAL_REVIEW
+    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
+    analysis_status: AnalysisStatus = "unavailable"
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    execution_allowed: Literal[False] = False
+    legacy_action: str | None = None
+    internal_intent: InternalSignalIntent = InternalSignalIntent.NONE
+    migration_version: str = "2.0"
+    gate_policy_version: str = "unavailable"
+    gate_policy_checksum: str = "unavailable"
+    schema_version: str = "2.0"
+
+    def __post_init__(self) -> None:
+        try:
+            object.__setattr__(self, "research_state", ResearchState(str(self.research_state)))
+        except ValueError:
+            object.__setattr__(self, "research_state", ResearchState.MANUAL_REVIEW)
+        try:
+            object.__setattr__(self, "portfolio_review_state", PortfolioReviewState(str(self.portfolio_review_state)))
+        except ValueError:
+            object.__setattr__(self, "portfolio_review_state", PortfolioReviewState.NOT_APPLICABLE)
+        if self.legacy_action is None:
+            object.__setattr__(self, "legacy_action", str(self.final_action).strip() or None)
+        if self.research_state is ResearchState.MANUAL_REVIEW:
+            object.__setattr__(self, "research_state", research_state_for_legacy_action(self.final_action))
+        if self.internal_intent is InternalSignalIntent.NONE:
+            object.__setattr__(self, "internal_intent", internal_intent_for_legacy_action(self.final_action))
+        if self.analysis_status == "unavailable":
+            if self.final_score_10 is None:
+                derived: AnalysisStatus = "unavailable"
+            elif self.warnings:
+                derived = "partial"
+            else:
+                derived = "complete"
+            object.__setattr__(self, "analysis_status", derived)
+        # This task only defines the compatibility seam.  Promotion remains
+        # disabled until the policy-driven gate resolver in Task 3.
+        object.__setattr__(self, "execution_allowed", False)
+
+    def to_v2_dict(self) -> dict[str, object]:
+        return public_authority_payload(
+            research_state=self.research_state,
+            portfolio_review_state=self.portfolio_review_state,
+            analysis_status=self.analysis_status,
+            research_promotion_allowed=self.research_promotion_allowed,
+            portfolio_review_allowed=self.portfolio_review_allowed,
+            legacy_action=self.legacy_action,
+            migration_version=self.migration_version,
+            gate_policy_version=self.gate_policy_version,
+            gate_policy_checksum=self.gate_policy_checksum,
+        )
+
+    def to_public_dict(self) -> dict[str, object]:
+        return self.to_v2_dict()

     @property
     def valid_component_count(self) -> int:
@@ -369,7 +435,17 @@ def build_simple_instrument_scores(
     )


-def simple_scoreboard_frame(scores: list[SimpleInstrumentScore]) -> pd.DataFrame:
+def simple_scoreboard_frame(
+    scores: list[SimpleInstrumentScore],
+    *,
+    include_legacy: bool = False,
+) -> pd.DataFrame:
+    """Build the v2 scoreboard frame.
+
+    Legacy ``final_action`` can be requested by diagnostic/compatibility
+    callers, but is not part of the release-facing default frame.
+    """
+
     rows: list[dict[str, object]] = []
     for score in scores:
         row: dict[str, object] = {
@@ -388,7 +464,17 @@ def simple_scoreboard_frame(scores: list[SimpleInstrumentScore]) -> pd.DataFrame
             "evidence_quality_10": score.evidence_quality_10,
             "risk_friction_10": score.risk_friction_10,
             "final_label": score.final_label,
-            "final_action": score.final_action,
+            "research_state": score.research_state.value,
+            "portfolio_review_state": score.portfolio_review_state.value,
+            "analysis_status": score.analysis_status,
+            "research_promotion_allowed": score.research_promotion_allowed,
+            "portfolio_review_allowed": score.portfolio_review_allowed,
+            "execution_allowed": False,
+            "legacy_action": score.legacy_action,
+            "migration_version": score.migration_version,
+            "gate_policy_version": score.gate_policy_version,
+            "gate_policy_checksum": score.gate_policy_checksum,
+            "schema_version": "2.0",
             "decision": score.decision,
             "blocked_by": ", ".join(score.warnings),
             "reason_short": score.one_line_reason,
@@ -432,6 +518,8 @@ def simple_scoreboard_frame(scores: list[SimpleInstrumentScore]) -> pd.DataFrame
             "total_components": score.total_component_count,
             "source_quality": "research_grade_yfinance",
         }
+        if include_legacy:
+            row["final_action"] = score.final_action
         for component in score.components:
             row[f"{component.key}_score_10"] = component.score_10
             row[f"{component.key}_status"] = component.status
diff --git a/tests/test_research_state_migration.py b/tests/test_research_state_migration.py
new file mode 100644
index 0000000..903c4b2
--- /dev/null
+++ b/tests/test_research_state_migration.py
@@ -0,0 +1,157 @@
+from __future__ import annotations
+
+import importlib
+import importlib.util
+from dataclasses import asdict, is_dataclass
+
+
+def _migration_module():
+    """Load the migration API without turning the RED run into an import error."""
+    spec = importlib.util.find_spec("etf_cockpit.governance.migrations")
+    assert spec is not None, "governance migration contract is not implemented"
+    return importlib.import_module("etf_cockpit.governance.migrations")
+
+
+def _payload(value):
+    if hasattr(value, "model_dump"):
+        return value.model_dump(mode="json")
+    if is_dataclass(value):
+        return asdict(value)
+    return dict(value)
+
+
+def test_v1_trim_migrates_lossily_and_preserves_original_value() -> None:
+    module = _migration_module()
+    migrated = module.migrate_legacy_action({"action": "trim", "schema_version": "1.0"})
+
+    assert migrated.research_state.value == "hold_review"
+    assert migrated.legacy_action == "trim"
+    assert migrated.migration_semantics == "lossy"
+    assert migrated.portfolio_review_state.value == "not_applicable"
+
+
+def test_legacy_mapping_and_unknown_values_fail_closed() -> None:
+    module = _migration_module()
+    expected = {
+        "buy": "research_candidate",
+        "add": "research_candidate",
+        "add_candidate": "research_candidate",
+        "hold": "hold_review",
+        "trim": "hold_review",
+        "trim_candidate": "hold_review",
+        "sell": "avoid",
+        "no_trade": "needs_evidence",
+        "manual_review": "manual_review",
+    }
+
+    for legacy, state in expected.items():
+        migrated = module.migrate_legacy_action({"action": legacy, "schema_version": "1.0"})
+        assert migrated.research_state.value == state
+        assert migrated.legacy_action == legacy
+        assert migrated.execution_allowed is False
+
+    unknown = module.migrate_legacy_action({"action": "invented_positive", "schema_version": "1.0"})
+    assert unknown.research_state.value == "manual_review"
+    assert unknown.legacy_action == "invented_positive"
+    assert unknown.research_promotion_allowed is False
+
+
+def test_migration_is_idempotent_and_v2_exports_have_no_legacy_action_field() -> None:
+    module = _migration_module()
+    first = module.migrate_legacy_action({"action": "add", "schema_version": "1.0"})
+    second = module.migrate_legacy_action(_payload(first))
+
+    assert _payload(first) == _payload(second)
+    payload = _payload(second)
+    assert payload["schema_version"] == "2.0"
+    assert payload["migration_version"] == "2.0"
+    assert payload["execution_allowed"] is False
+    assert "action" not in payload
+    assert "final_action" not in payload
+    assert payload["legacy_action"] == "add"
+
+
+def test_public_state_enums_do_not_expose_legacy_action_verbs() -> None:
+    module = importlib.import_module("etf_cockpit.signals.research_states")
+
+    assert "buy" not in module.ResearchState._value2member_map_
+    assert "sell" not in module.PortfolioReviewState._value2member_map_
+    assert set(module.InternalSignalIntent._value2member_map_) == {
+        "increase",
+        "maintain",
+        "decrease",
+        "exit",
+        "none",
+    }
+
+
+def test_portfolio_review_requires_explicit_snapshot_context() -> None:
+    module = _migration_module()
+    without_context = module.migrate_legacy_action({"action": "add", "schema_version": "1.0"})
+    with_unrelated_context = module.migrate_legacy_action(
+        {"action": "add", "schema_version": "1.0", "portfolio": {"notes": "not a snapshot"}}
+    )
+
+    assert without_context.portfolio_review_state.value == "not_applicable"
+    assert with_unrelated_context.portfolio_review_state.value == "not_applicable"
+    assert without_context.portfolio_review_allowed is False
+    assert with_unrelated_context.portfolio_review_allowed is False
+
+
+def test_explicit_snapshot_is_the_only_portfolio_review_context() -> None:
+    module = _migration_module()
+    migrated = module.migrate_legacy_action(
+        {
+            "action": "hold",
+            "schema_version": "1.0",
+            "portfolio_snapshot": {
+                "as_of_date": "2026-07-10",
+                "portfolio_review_state": "reduce_exposure_review",
+            },
+        }
+    )
+
+    assert migrated.portfolio_review_state.value == "reduce_exposure_review"
+    assert migrated.portfolio_review_allowed is True
+    assert migrated.execution_allowed is False
+
+
+def test_v2_public_signal_serialisation_has_typed_authority_fields_only() -> None:
+    from datetime import date
+
+    from etf_cockpit.core.types import ComponentScores, SignalResult
+
+    signal = SignalResult(
+        run_id="run",
+        signal_date=date(2026, 7, 10),
+        etf_id="VWCE",
+        action="add_candidate",
+        confidence=0.5,
+        total_score=0.4,
+        components=ComponentScores(*(0.0 for _ in range(12))),
+        blocked_by=[],
+        warnings=[],
+        reason_short="review",
+        reason_long="review",
+        horizon_primary="1-3 months",
+    )
+
+    payload = signal.to_v2_dict()
+    assert payload["research_state"] == "research_candidate"
+    assert payload["execution_allowed"] is False
+    assert "action" not in payload
+    assert "final_action" not in payload
+
+
+def test_resolve_research_state_fails_closed_when_components_are_unavailable() -> None:
+    module = importlib.import_module("etf_cockpit.signals.research_states")
+
+    decision = module.AuthorityDecision(
+        analysis_status="complete",
+        research_state=module.ResearchState.RESEARCH_CANDIDATE,
+        portfolio_review_state=module.PortfolioReviewState.NOT_APPLICABLE,
+        research_promotion_allowed=True,
+    )
+    component = module.ScoreComponent(key="momentum", status="unavailable", score=None)
+
+    assert module.resolve_research_state([component], decision) is module.ResearchState.NOT_SCOREABLE
