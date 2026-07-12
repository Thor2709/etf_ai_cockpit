# Task completed

Fresh read-only re-review of `2a26619bdbf26f11e8a77dbdefc3ab22d93d213b..ce5c521`, including the supplied brief, report, review package, prior rejection, complete committed file range, fixed resolver and relevant release/export paths.

SPECIFICATION: **REJECT**.

CODE QUALITY: **REJECT**.

READY: **NO**.

# Files and symbols examined

- `src/etf_cockpit/governance/gate_policy.py`: `PortfolioContext.usable`, `_coerce_gate`, `_policy_metadata`, `resolve_authority`.
- `src/etf_cockpit/signals/research_states.py`: `GateSeverity`, `GateResult`, `AuthorityDecision`, `resolve_research_state`, `public_authority_payload`.
- `src/etf_cockpit/core/types.py`: `SignalResult.__post_init__`, `SignalResult.to_v2_dict`, `DataQualityReport.analysis_allowed`, `DataQualityReport.trading_allowed`.
- Production authority/export seams in `signals/simple_scores.py`, `signals/gates.py`, `services.py`, `portfolio/proposals.py`, `audit/local_llm.py`, `chatgpt_bridge/export_pack.py`, `chatgpt_bridge/schemas.py` and `data/score_history.py`.
- `configs/gate_policy.yaml`, `tests/test_authority_resolution.py`, focused governance/release tests and the complete base-to-HEAD changed-file list.

# Findings or changes

1. **BLOCKING - the new authority resolver is not consumed by any production release path.** Observation: the only calls to `resolve_authority` in the repository are in `tests/test_authority_resolution.py`; no production module imports or invokes it. Release-facing `SignalResult` and `SimpleScoreResult` compatibility paths continue to force promotion/review flags false and retain default `gate_policy_version`/`gate_policy_checksum` values of `unavailable`. Inference: the resolver's policy-ordered `GateResult` table, severity decisions and checksum metadata cannot reach actual release/export output. This does not satisfy the brief's required outcome that the typed decision and ordered gate table are consumed by release paths.

2. **FIX CONFIRMED - policy severity is authoritative.** `resolve_authority` replaces caller severity with `policy_entry.severity` before evaluating failures. A caller-labelled identity notice still resolves as a failed blocker and cannot promote.

3. **FIX CONFIRMED - configured gate evidence is complete and unique before positive authority.** Unknown and duplicate IDs fail closed, and lines 149-151 reject any missing configured ID. Adversarial removal of each of the nine configured rows independently returned unavailable diagnostic authority.

4. **FIX CONFIRMED - portfolio context validation is evidence-bearing and closed to extras.** `PortfolioContext` uses `extra="forbid"`; `usable` requires `validated=True`, a non-`not_applicable` state, a date and exactly 64 hexadecimal checksum characters. Missing date, short, non-hex or unavailable checksums cannot grant portfolio review; an extra field produces an unavailable diagnostic decision.

5. **Other required semantics confirmed.** Failed blockers are monotonic; configured warnings remain visible and downgrade a candidate; a configured notice remains visible without changing the base candidate; malformed and unknown inputs carry diagnostics and unavailable metadata; valid decisions propagate identical policy version/checksum metadata to every row. `AuthorityDecision` rejects `execution_allowed=True`. `DataQualityReport.trading_allowed` emits `DeprecationWarning` and returns literal `False`, including for a clean report. No Task 4 journal/review-report implementation, Task 5 UI, broker, order-routing or credential scope is present in the committed range.

# Evidence

- `gate_policy.py:138-151`: policy entry lookup overwrites severity and then checks the configured-ID set for omissions; duplicate detection is at lines 135-136.
- `gate_policy.py:30-46`: extra fields are forbidden and portfolio usability requires validated state, date and a 64-character hexadecimal checksum.
- `gate_policy.py:157-196`: blocker/warning evaluation is monotonic; execution is fixed false and policy metadata is returned on the decision.
- Repository call-path search: `rg -n "resolve_authority|PortfolioContext|AuthorityDecision\\(" src tests -g '*.py'` found resolver calls only at `tests/test_authority_resolution.py:36-183`; production contains only the resolver definition and `AuthorityDecision` construction internal to it.
- `core/types.py:125-132,155-157` and `signals/simple_scores.py:226-233,256-266`: release-facing compatibility objects default policy metadata to unavailable and forcibly neutralise authority flags rather than consuming `AuthorityDecision`.
- Adversarial output: all nine configured IDs were required; duplicate evidence was diagnostic; spoofed failed identity resolved `not_scoreable`; failed warning resolved `manual_review`; mocked configured notice remained visible; valid portfolio evidence allowed review, while invalid checksum/date/extra-field cases did not; execution remained false; metadata was `2026-07-12` / `9b06166c05c60cf1dec7214c2aaa2b9b7e59804bdcfcf0b19195c2a09470d6bb`.
- `git diff --name-only` and scope search found no UI/Flet, journal replacement, review-report implementation, broker, order, credential or execution feature file in the committed range.

# Commands or tests run

- Focused authority/release bundle: `$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_authority_resolution.py tests\\test_signal_gates.py tests\\test_release_hardening.py -q --tb=short` - exit 0, **46 passed**.
- Affected governance/migration/proposal/export bundle from the review package - exit 0, **88 passed**; two existing pandas `FutureWarning`s only.
- Inline adversarial Python probe - exit 0; exercised severity spoofing, each missing row, duplicate row, warning downgrade, configured-notice visibility, metadata propagation, valid/invalid portfolio contexts and extra-field rejection.
- Inline compatibility probe - exit 0; clean `trading_allowed` returned false with one `DeprecationWarning`, and Pydantic rejected `AuthorityDecision(execution_allowed=True)`.
- `git diff --check 2a26619bdbf26f11e8a77dbdefc3ab22d93d213b..ce5c521` - exit 0, no output.
- `git status --short` - only the four pre-existing generated schema-version files were modified; this review did not alter them.

# Remaining uncertainty and risk

The focused and affected bundles do not expose the integration omission because they test the resolver directly and existing release compatibility behaviour separately. Until a production authority assembly path constructs the nine gate rows, invokes `resolve_authority`, and propagates its decision/table into release/export consumers, the new semantics remain test-only. The recorded authoritative full suite was not rerun because the review package already evidences its seven known generated-data/identity baseline failures and the requested focused bundles are current.

# Recommended next action

Integrate `resolve_authority` at the production release-authority assembly boundary, propagate its ordered gates and policy metadata through the existing typed release/export contracts without widening Task 4/5 scope, add an end-to-end release-path regression, rerun the two focused bundles, and request another independent review.

Verdict: reject with blocking findings.
