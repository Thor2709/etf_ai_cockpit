# Task completed

Independent final review of the stable Wave 1 Governance Task 2 diff against base `7735afd46b96c4d327754709c8040f98f7bd88fa`.

SPECIFICATION: FAIL
CODE QUALITY: FAIL
READY: NO

Verdict: reject with blocking findings.

# Files and symbols examined

- `src/etf_cockpit/governance/migrations.py`: `ResearchStateMigration`, `from_validated_snapshot`, `_snapshot_payload_is_valid`, `_v2_context_marker`, `migrate_legacy_action`.
- `src/etf_cockpit/signals/research_states.py`: enums, `AuthorityDecision`, `_component_is_model_only`, `resolve_research_state`, `public_authority_payload`.
- `src/etf_cockpit/data/score_history.py`: `append_score_run`, `_snapshot_context_for_row`, `score_history_v2_payload`.
- `src/etf_cockpit/core/types.py`: `SignalResult.__post_init__`, `to_v2_dict`.
- `src/etf_cockpit/signals/simple_scores.py`: `SimpleInstrumentScore.__post_init__`, `to_v2_dict`, `simple_scoreboard_frame`.
- `src/etf_cockpit/signals/actions.py`, `signal_pipeline.py`, and ChatGPT schema/import/export/validation paths.
- Approved plan, Task 2 brief/report, and both prior independent reviews.

# Findings or changes

- **Blocking - Important - strict v2 model contract is not enforced.** `ResearchStateMigration` declares `migration_version` and `schema_version` as unrestricted `str` fields (`src/etf_cockpit/governance/migrations.py:71,74`). Direct construction therefore accepts and serialises non-v2 values, despite this being the exposed canonical v2 row and despite the acceptance requirement that release-facing rows carry `migration_version=2.0` and `schema_version=2.0`. `ConfigDict(extra="forbid")` does not constrain these values. This is specification non-compliance and leaves a compatibility path capable of producing a falsely labelled public record.
- No other blocking or non-blocking correctness finding was identified in the reviewed paths. The current migration function maps v1 values conservatively, rejects unsupported input schema versions, preserves deterministic idempotence, validates retained snapshots and checksums, rejects forged marker-only context, ignores caller-supplied v2 authority flags, and fixes `execution_allowed=False`.
- Model-only evidence, including `score_role="model_confirmation"`, cannot promote. Score-history retains canonical snapshot JSON/checksum provenance and does not recreate review authority from marker flags alone. ChatGPT v2 models reject legacy action extras, while v1 imports remain supported.
- Observation: legacy `final_action` remains inside `SignalResult.supporting_metrics` construction (`src/etf_cockpit/signals/signal_pipeline.py:156`) as an internal compatibility value; the inspected release serializer `_signal_to_json` uses `SignalResult.to_v2_dict` and does not publish that mapping. No Task 3 central gate resolver or Task 4 journal/review-report implementation was found.

# Evidence

- Reproduction: direct `ResearchStateMigration(research_state=ResearchState.MANUAL_REVIEW, schema_version="9.9", migration_version="bogus").model_dump()` succeeds and emits both invalid version strings.
- `migrate_legacy_action` itself constrains input versions at `migrations.py:308-315` and emits `2.0`; the defect is specifically the public model's direct validation/serialisation boundary.
- Snapshot integrity is checked at `migrations.py:101-105,126-133,322-334`; v2 flags are normalised at `migrations.py:77-82,386-396`; model confirmation is excluded at `research_states.py:206-214`; release authority payload fixes execution false and excludes `action`/`final_action` at `research_states.py:280-310`.

# Commands or tests run

- `$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_research_state_migration.py tests\\test_score_history.py tests\\test_chatgpt_import.py tests\\test_trade_proposals.py -q` - **37 passed**, with two existing pandas `FutureWarning`s.
- `$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -c "...ResearchStateMigration(... schema_version='9.9', migration_version='bogus').model_dump()"` - exited 0 and reproduced the invalid public payload.
- Read-only `git status`, `git diff --stat`, `git diff --name-only`, scoped `rg`, and line-numbered source inspection against the stated base.

# Remaining uncertainty and risk

- The focused suite does not cover direct invalid version construction, so its green result cannot protect this boundary.
- The authoritative full suite was not rerun during this final review; the implementation report records seven pre-existing generated-data/identity failures. This does not alter the blocking schema finding.

# Recommended next action

Constrain `ResearchStateMigration.schema_version` and `migration_version` to the fixed v2 contract, add direct-construction rejection tests, then rerun the 37-test focused command and scoped lint/compile checks before re-review.
