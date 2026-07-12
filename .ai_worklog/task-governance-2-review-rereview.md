SPECIFICATION: FAIL
CODE QUALITY: FAIL

FINDING: IMPORTANT — validated snapshot markers are trusted without source evidence or an integrity check; `migrate_legacy_action` (`src/etf_cockpit/governance/migrations.py`, `_v2_context_marker`, `migrate_legacy_action`) grants `portfolio_review_allowed=True` for a v2 row that only supplies `portfolio_snapshot_validated=True`, `portfolio_snapshot_provenance=validated_snapshot`, and a review state. The same trust exists in `score_history.py` (`_snapshot_context_for_row`). A caller can therefore recreate portfolio authority without a contemporaneous snapshot. The marker does preserve idempotency for genuine migration output, but it is not itself validated.

FINDING: IMPORTANT — v2 authority flags are not enforced by the public models; `src/etf_cockpit/governance/migrations.py`, `ResearchStateMigration`, and `src/etf_cockpit/chatgpt_bridge/schemas.py`, `PortfolioReviewAudit`, accept caller-supplied `research_promotion_allowed=True` and `portfolio_review_allowed=True` and emit them through `to_v2_dict`/`model_dump`. The migration function and dataclass compatibility seams force flags false, but direct v2 model construction remains an authority-inflation path before Task 3.

FINDING: IMPORTANT — model-confirmation evidence can still promote a candidate; `src/etf_cockpit/signals/research_states.py`, `_component_is_model_only` does not classify the repository's `score_role="model_confirmation"` as model-only. A component with that role, an allow-listed non-model-looking source ID, a finite score and status `ok` can satisfy `resolve_research_state` and return `research_candidate`.

FINDING: MINOR — v2 audit return type remains stale at a caller boundary; `src/etf_cockpit/services.py`, `ChatGPTBridge.import_audit_json` is annotated `-> ChatGPTAudit` although `import_audit_json` now returns `ChatGPTAudit | ChatGPTAuditV2`. This loses the v2 type contract for service callers even though `validate_audit_file` itself was corrected.

READY: NO
