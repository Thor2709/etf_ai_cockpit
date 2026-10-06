"""Top-N selection and portfolio-goals workspaces for presentation (application; ADR-0002)."""

from collections.abc import (
    Mapping,
    Sequence,
)
from datetime import (
    date,
    datetime,
    timezone,
)
import hashlib
import json
from pathlib import Path
import sqlite3
import pandas as pd

from etf_cockpit.core.paths import LOG_DIR
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    TransactionalStore,
    storage_layout,
)
from etf_cockpit.portfolio.top_n_selection import (
    SelectionCandidate,
    SelectionPolicyError,
    build_selection_run,
    load_selection_policy,
    persist_selection_run,
)
from etf_cockpit.portfolio.selection_slices import materialise_selection_slices
from etf_cockpit.models.forecast_scores import PRIMARY_MODEL_HORIZON_DAYS
from etf_cockpit.portfolio.sandbox import PortfolioAnalysis
from etf_cockpit.portfolio.goals_constraints import (
    PORTFOLIO_GOALS_SCHEMA,
    PortfolioPolicy,
    alert_record,
    build_alerts,
    build_what_if_scenario,
    policy_editor_value,
    policy_from_record,
    policy_record,
    source_snapshot_hash,
    validate_portfolio_policy,
    what_if_record,
)
from etf_cockpit.application.identity_views import load_classification_projection
from etf_cockpit.application.fixed_income_views import load_fixed_income_screener
from etf_cockpit.application.portfolio_views import (
    load_portfolio_calendar_projection,
    load_portfolio_forecast_aggregation,
)
from etf_cockpit.application.decision_views import load_opportunity_assessment


def load_top_n_selection(
    *,
    candidates: Sequence[SelectionCandidate] | None = None,
    mode: str = "cross_asset",
    decision_time: str | None = None,
    top_n: int | None = None,
    seed: int | None = None,
    portfolio_snapshot: Mapping[str, object] | None = None,
    reference_anchor: object | None = None,
    portfolio_policy: object | None = None,
    risk_profile: object | None = None,
    snapshot: object | None = None,
    storage_root: Path | None = None,
) -> dict[str, object]:
    """Build from saved, point-in-time evidence and persist an immutable run."""

    root = Path(storage_root or ROOT).resolve()
    try:
        policy = load_selection_policy()
    except SelectionPolicyError as exc:
        return {
            "contract": "selection-run.v1",
            "status": "unavailable",
            "mode": "unavailable",
            "reason": str(exc),
            "selected_ids": [],
            "candidate_table": [],
            "exclusion_funnel": [],
            "policy": None,
            "persistence_status": "not_attempted",
            "execution_allowed": False,
        }

    if not decision_time:
        return {
            "contract": "selection-run.v1",
            "status": "unavailable",
            "mode": "unavailable",
            "reason": "selection_decision_time_unavailable",
            "selected_ids": [],
            "candidate_table": [],
            "exclusion_funnel": [],
            "policy": policy.to_record(),
            "persistence_status": "not_attempted",
            "execution_allowed": False,
        }

    if candidates is None:
        from dataclasses import fields

        from etf_cockpit.analysis.decision.contracts import OpportunityResult
        from etf_cockpit.application.bulk_run import BulkAnalysisService
        from etf_cockpit.portfolio.benchmark_reference_contract import resolve_vwce_anchor
        from etf_cockpit.portfolio.goals_constraints import policy_from_record
        from etf_cockpit.portfolio.risk_profiles import (
            VWCEAnchorSnapshot,
            RiskProfileVersion,
            load_risk_profile_presets,
            risk_profile_preset_version,
            risk_profile_version_from_record,
        )

        try:
            cutoff = pd.Timestamp(decision_time)
        except (TypeError, ValueError, OverflowError):
            return {
                "contract": "selection-run.v1",
                "status": "unavailable",
                "mode": "unavailable",
                "reason": "selection_decision_time_invalid",
                "selected_ids": [],
                "candidate_table": [],
                "exclusion_funnel": [],
                "policy": policy.to_record(),
                "persistence_status": "not_attempted",
                "execution_allowed": False,
            }
        if cutoff.tzinfo is None:
            return {
                "contract": "selection-run.v1",
                "status": "unavailable",
                "mode": "unavailable",
                "reason": "selection_decision_time_invalid",
                "selected_ids": [],
                "candidate_table": [],
                "exclusion_funnel": [],
                "policy": policy.to_record(),
                "persistence_status": "not_attempted",
                "execution_allowed": False,
            }
        cutoff = cutoff.tz_convert("UTC")

        def _known_by_cutoff(value: object) -> bool:
            try:
                timestamp = pd.Timestamp(value)
                return bool(timestamp.tzinfo is not None and timestamp.tz_convert("UTC") <= cutoff)
            except (TypeError, ValueError, OverflowError):
                return False

        def _record_time(value: Mapping[str, object]) -> object | None:
            return next(
                (value.get(name) for name in ("decision_time", "as_of", "known_at") if value.get(name)),
                None,
            )

        bulk_outputs: dict[str, tuple[Mapping[str, object], str, str]] = {}
        instrument_ids: set[str] = set()
        try:
            bulk_service = BulkAnalysisService(root)
            workflows = bulk_service.scheduler.list_workflows(limit=200)
            for workflow in workflows:
                if workflow.workflow_type != BulkAnalysisService.workflow_type:
                    continue
                if not _known_by_cutoff(workflow.created_at):
                    continue
                bulk_run = bulk_service.get_run(workflow.workflow_id)
                jobs = bulk_service.scheduler.list_jobs(workflow.workflow_id)
                finished_by_id = {
                    str(job.inputs.get("instrument_id")): str(job.finished_at)
                    for job in jobs
                    if isinstance(job.inputs, Mapping)
                    and job.inputs.get("instrument_id")
                    and job.finished_at
                    and _known_by_cutoff(job.finished_at)
                }
                for instrument_id, output in bulk_run.results.items():
                    clean_id = str(instrument_id).strip()
                    if not clean_id:
                        continue
                    instrument_ids.add(clean_id)
                    if not isinstance(output, Mapping):
                        continue
                    known_at = _record_time(output) or finished_by_id.get(clean_id)
                    if known_at is None or not _known_by_cutoff(known_at):
                        continue
                    bulk_outputs.setdefault(
                        clean_id,
                        (dict(output), str(known_at), str(bulk_run.hashes.get(clean_id, ""))),
                    )
        except (AttributeError, KeyError, OSError, sqlite3.Error, TypeError, ValueError):
            bulk_outputs = {}

        universe = getattr(getattr(snapshot, "config", None), "universe", None)
        by_id = getattr(universe, "by_id", None)
        if callable(by_id):
            try:
                instrument_ids.update(str(value).strip() for value in by_id() if str(value).strip())
            except (TypeError, ValueError):
                pass

        try:
            fixed_screen = load_fixed_income_screener(
                storage_root=root,
                decision_time=decision_time,
            )
        except (OSError, TypeError, ValueError):
            fixed_screen = {"status": "unavailable", "rows": [], "decision_time": decision_time}
        fixed_rows_raw = fixed_screen.get("rows", ())
        fixed_rows = {
            str(row.get("instrument_id", "")).strip(): dict(row)
            for row in fixed_rows_raw
            if isinstance(row, Mapping) and str(row.get("instrument_id", "")).strip()
        } if isinstance(fixed_rows_raw, Sequence) else {}
        instrument_ids.update(fixed_rows)

        artifact_directory = LOG_DIR
        try:
            artifact_directory = root / LOG_DIR.relative_to(ROOT)
        except ValueError:
            pass
        opportunity_fields = {item.name for item in fields(OpportunityResult)}
        tuple_fields = {"domain_scores", "positive_drivers", "negative_drivers", "benchmark_rankers"}
        candidates_list: list[SelectionCandidate] = []
        for instrument_id in sorted(instrument_ids):
            try:
                saved_opportunity = load_opportunity_assessment(
                    instrument_id,
                    decision_time=decision_time,
                    artifact_directory=artifact_directory,
                )
                opportunity_values = {
                    key: value for key, value in saved_opportunity.items()
                    if key in opportunity_fields
                }
                for field_name in tuple_fields:
                    if isinstance(opportunity_values.get(field_name), list):
                        opportunity_values[field_name] = tuple(opportunity_values[field_name])
                opportunity = OpportunityResult(**opportunity_values)
            except (KeyError, TypeError, ValueError):
                continue

            output_entry = bulk_outputs.get(instrument_id)
            output = output_entry[0] if output_entry is not None else {}
            metric_values: dict[str, object] = {}
            pending = [output]
            while pending:
                current = pending.pop()
                if not isinstance(current, Mapping):
                    continue
                for key in ("net_expected_return", "downside_risk", "marginal_impact", "liquidity", "cost", "evidence"):
                    if key not in metric_values and current.get(key) is not None:
                        metric_values[key] = current[key]
                pending.extend(value for value in current.values() if isinstance(value, Mapping))

            fixed_row = fixed_rows.get(instrument_id, {})
            if metric_values.get("net_expected_return") is None and fixed_row.get("net_total_return") is not None:
                metric_values["net_expected_return"] = fixed_row["net_total_return"]
            if metric_values.get("downside_risk") is None and fixed_row.get("loss_probability") is not None:
                metric_values["downside_risk"] = fixed_row["loss_probability"]
            if metric_values.get("evidence") is None:
                metric_values["evidence"] = opportunity.confidence

            country = None
            sector = None
            try:
                classification = load_classification_projection(
                    instrument_id,
                    storage_root=root,
                    effective_at=decision_time,
                    decision_time=decision_time,
                )
                classification_value = classification.get("classification")
                if isinstance(classification_value, Mapping):
                    country = classification_value.get("country")
                    sector = classification_value.get("sector")
            except (OSError, TypeError, ValueError):
                pass
            country = country or fixed_row.get("country")
            sector = sector or fixed_row.get("issuer_sector")
            common_times = [opportunity.decision_time]
            if output_entry is not None:
                common_times.append(output_entry[1])
            if fixed_row and fixed_screen.get("decision_time"):
                common_times.append(str(fixed_screen["decision_time"]))
            source_hashes = [("opportunity_universe", opportunity.universe_hash),
                             ("opportunity_policy", opportunity.config_hash),
                             ("opportunity_vintage", opportunity.source_vintage_hash)]
            if output_entry is not None and output_entry[2]:
                source_hashes.append(("bulk_run", output_entry[2]))
            if fixed_row and fixed_screen.get("analysis_snapshot_id"):
                source_hashes.append(("fixed_income_screener", str(fixed_screen["analysis_snapshot_id"])))
            candidates_list.append(
                SelectionCandidate(
                    opportunity=opportunity,
                    common_metrics_as_of=max(
                        pd.Timestamp(value).tz_convert("UTC") for value in common_times
                    ).isoformat(),
                    country=None if country is None else str(country),
                    sector=None if sector is None else str(sector),
                    net_expected_return=metric_values.get("net_expected_return"),
                    downside_risk=metric_values.get("downside_risk"),
                    marginal_impact=metric_values.get("marginal_impact"),
                    liquidity=metric_values.get("liquidity"),
                    cost=metric_values.get("cost"),
                    evidence=metric_values.get("evidence"),
                    source_hashes=tuple(source_hashes),
                )
            )
        candidates = tuple(candidates_list)
        if not candidates:
            return {
                "contract": "selection-run.v1",
                "status": "unavailable",
                "mode": mode if mode in {"asset_specific", "cross_asset"} else "unavailable",
                "reason": "frozen_opportunity_candidates_unavailable",
                "decision_time": decision_time,
                "top_n": policy.top_n if top_n is None else top_n,
                "seed": seed,
                "policy": policy.to_record(),
                "candidate_table": [],
                "selected_ids": [],
                "exclusion_funnel": [],
                "source_snapshot_hashes": {},
                "portfolio_reference": None,
                "persistence_status": "not_attempted",
                "execution_allowed": False,
            }

        if portfolio_snapshot is None and snapshot is not None:
            candidate_snapshot = getattr(snapshot, "portfolio_snapshot", None)
            if isinstance(candidate_snapshot, Mapping):
                portfolio_snapshot = dict(candidate_snapshot)
            else:
                binding = getattr(snapshot, "candidate_price_binding", None)
                binding = binding if isinstance(binding, Mapping) else {}
                portfolio_id = getattr(snapshot, "portfolio_id", None)
                snapshot_id = getattr(snapshot, "snapshot_id", binding.get("snapshot_id"))
                as_of = getattr(snapshot, "as_of", binding.get("as_of"))
                if portfolio_id and snapshot_id and as_of:
                    holdings = getattr(snapshot, "holdings", None)
                    portfolio_snapshot = {
                        "portfolio_id": str(portfolio_id),
                        "snapshot_id": str(snapshot_id),
                        "as_of": str(as_of),
                        "holdings": holdings.to_dict(orient="records") if isinstance(holdings, pd.DataFrame) else [],
                    }

        if reference_anchor is None and portfolio_snapshot is None and snapshot is not None:
            supplied_anchor = getattr(snapshot, "vwce_anchor_snapshot", None)
            if isinstance(supplied_anchor, VWCEAnchorSnapshot):
                reference_anchor = supplied_anchor
            else:
                evidence = getattr(snapshot, "vwce_anchor_evidence", None)
                listing_id = getattr(snapshot, "vwce_listing_id", None)
                currency = getattr(snapshot, "benchmark_reference_currency", None)
                horizon = getattr(snapshot, "benchmark_reference_horizon_years", None)
                effective_date = getattr(snapshot, "benchmark_reference_end_date", None)
                if evidence is not None and listing_id and currency and horizon and effective_date:
                    try:
                        resolved = resolve_vwce_anchor(
                            evidence,
                            listing_id=str(listing_id),
                            effective_date=str(effective_date),
                            decision_time=decision_time,
                            currency=str(currency),
                            horizon_years=float(horizon),
                            conversion_evidence=getattr(snapshot, "vwce_conversion_evidence", None),
                        )
                        reference_anchor = VWCEAnchorSnapshot(
                            status="available" if resolved.status == "available" else "unavailable",
                            reason=resolved.reason,
                            canonical_share_class_id=resolved.canonical_share_class_id,
                            listing_id=resolved.listing_id,
                            effective_date=resolved.effective_date,
                            knowledge_cutoff=resolved.decision_time,
                            output_currency=resolved.output_currency,
                            horizon_years=resolved.horizon_years,
                            anchor_digest=resolved.anchor_digest,
                            resolution_digest=resolved.replay_digest,
                            risk_envelope_status="unavailable",
                            risk_metrics=(),
                        )
                    except (TypeError, ValueError):
                        reference_anchor = None

        if portfolio_policy is None and snapshot is not None:
            try:
                goals = load_portfolio_goals_projection(snapshot, root=root)
                versions = goals.get("policy_history", ())
                if isinstance(versions, Sequence) and not isinstance(versions, (str, bytes)):
                    usable_versions = [
                        item for item in versions
                        if isinstance(item, Mapping)
                        and item.get("saved_at")
                        and _known_by_cutoff(item.get("saved_at"))
                    ]
                    if usable_versions:
                        portfolio_policy = policy_from_record(usable_versions[-1])
            except (OSError, TypeError, ValueError):
                portfolio_policy = None

        if risk_profile is None:
            supplied_profile = getattr(snapshot, "risk_profile", None) if snapshot is not None else None
            if isinstance(supplied_profile, RiskProfileVersion):
                risk_profile = supplied_profile
            elif isinstance(supplied_profile, Mapping):
                try:
                    risk_profile = risk_profile_version_from_record(supplied_profile)
                except (TypeError, ValueError):
                    risk_profile = None
            if risk_profile is None:
                try:
                    presets = load_risk_profile_presets()
                    default_profile = next(item for item in presets if item.profile_id == "medium")
                    risk_profile = risk_profile_preset_version(default_profile)
                except (StopIteration, OSError, TypeError, ValueError):
                    risk_profile = None

    try:
        run = build_selection_run(
            candidates,
            decision_time=decision_time,
            mode=mode,  # type: ignore[arg-type]
            policy=policy,
            top_n=top_n,
            seed=seed,
            portfolio_snapshot=portfolio_snapshot,
            reference_anchor=reference_anchor,
            portfolio_policy=portfolio_policy,  # type: ignore[arg-type]
            risk_profile=risk_profile,  # type: ignore[arg-type]
        )
        with TransactionalStore(root) as store:
            stored = persist_selection_run(store, run)
    except (OSError, StorageSchemaError, sqlite3.DatabaseError, TypeError, ValueError) as exc:
        return {
            "contract": "selection-run.v1",
            "status": "unavailable",
            "mode": "unavailable",
            "reason": "selection_run_unavailable:" + str(exc),
            "selected_ids": [],
            "candidate_table": [],
            "exclusion_funnel": [],
            "policy": policy.to_record(),
            "persistence_status": "failed",
            "execution_allowed": False,
        }
    return {
        **run.to_record(),
        "slices": materialise_selection_slices(run),
        "persistence_status": "persisted",
        "persistence_revision": stored.revision,
    }


def load_portfolio_goals_projection(
    snapshot: object,
    analysis: PortfolioAnalysis | None = None,
    *,
    action: Mapping[str, object] | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    """Load revisioned portfolio goals and snapshot-bound what-if evidence.

    The optional action is one of ``save_policy``, ``simulate``,
    ``acknowledge`` or ``snooze``. State uses the existing transactional user
    store; candidate analysis and alert evidence remain advisory and never
    write portfolio ledger entries.
    """

    binding = getattr(analysis, "snapshot_binding", None) if analysis is not None else None
    account_id = str(getattr(binding, "account_id", getattr(snapshot, "account_id", "default")) or "default")
    portfolio_id = str(getattr(binding, "portfolio_id", getattr(snapshot, "portfolio_id", "default")) or "default")
    storage_id = hashlib.sha256(f"{account_id}\0{portfolio_id}".encode("utf-8")).hexdigest()
    entity_type = PORTFOLIO_GOALS_SCHEMA
    command = dict(action) if isinstance(action, Mapping) else None
    command_type = str(command.get("type", "")) if command is not None else ""
    state: dict[str, object] = {
        "schema_version": PORTFOLIO_GOALS_SCHEMA,
        "policy_versions": [],
        "scenarios": [],
        "acknowledgement_history": [],
    }
    stored_revision = 0

    try:
        layout = storage_layout(root)
        database_exists = layout.transactional_path.is_file()
        if database_exists or command is not None:
            with TransactionalStore(root, read_only=command is None) as store:
                record = store.get(entity_type, storage_id)
                if record is not None:
                    if record.payload.get("schema_version") != PORTFOLIO_GOALS_SCHEMA:
                        return _portfolio_goals_unavailable("stored_portfolio_goals_schema_invalid")
                    state = dict(record.payload)
                    stored_revision = record.revision
                if command is not None:
                    if not isinstance(state.get("policy_versions"), list) or not isinstance(state.get("scenarios"), list) or not isinstance(state.get("acknowledgement_history"), list):
                        return _portfolio_goals_unavailable("stored_portfolio_goals_history_invalid")
                    versions = list(state["policy_versions"])
                    active_record = versions[-1] if versions else None
                    latest_policy = policy_from_record(active_record)
                    if versions and latest_policy is None:
                        return _portfolio_goals_unavailable("stored_portfolio_policy_invalid")
                    active_policy = _portfolio_goals_policy_as_of(versions, analysis)
                    policy_id = f"portfolio-goals:{storage_id}"
                    if active_policy is None:
                        active_policy = PortfolioPolicy(policy_id=policy_id, version=0)
                    evidence = _portfolio_goals_evidence(snapshot, analysis, active_policy, command_type)
                    current_hash = source_snapshot_hash(analysis) if analysis is not None else None
                    alerts, unavailable_alerts = build_alerts(
                        analysis,
                        active_policy,
                        snapshot=snapshot,
                        evidence=evidence,
                        snapshot_hash=current_hash,
                    ) if analysis is not None else ((), ({"kind": "all", "status": "unavailable", "reason": "analysis_unavailable"},))
                    acknowledgement_history = list(state["acknowledgement_history"])
                    scenarios = list(state["scenarios"])
                    saved_at = _portfolio_goals_action_time(command.get("at"))

                    if command_type == "save_policy":
                        raw_policy = command.get("policy")
                        next_policy = validate_portfolio_policy(
                            raw_policy,
                            policy_id=f"portfolio-goals:{storage_id}",
                            version=len(versions) + 1,
                        )
                        _validate_portfolio_goal_identifiers(next_policy, snapshot)
                        versions.append(policy_record(next_policy, saved_at=saved_at))
                    elif command_type == "simulate":
                        if analysis is None:
                            return _portfolio_goals_unavailable("what_if_analysis_unavailable")
                        scenario_policy = latest_policy or PortfolioPolicy(policy_id=policy_id, version=0)
                        scenario_evidence = _portfolio_goals_evidence(
                            snapshot, analysis, scenario_policy, command_type
                        )
                        forecast = None
                        try:
                            forecast = load_portfolio_forecast_aggregation(
                                snapshot,
                                analysis,
                                horizon_days=PRIMARY_MODEL_HORIZON_DAYS,
                            )
                        except (ArithmeticError, KeyError, TypeError, ValueError, AttributeError):
                            forecast = {"status": "unavailable", "reason": "canonical_portfolio_forecast_unavailable"}
                        scenario = build_what_if_scenario(
                            analysis,
                            snapshot,
                            scenario_policy,
                            evidence=scenario_evidence,
                            forecast=forecast,
                        )
                        scenario_value = what_if_record(scenario)
                        scenario_value["policy_binding"] = _portfolio_goals_policy_binding(scenario_policy)
                        scenario_value["saved_at"] = saved_at
                        scenarios.append(scenario_value)
                    elif command_type in {"acknowledge", "snooze"}:
                        if analysis is None or current_hash is None:
                            return _portfolio_goals_unavailable("alert_source_snapshot_unavailable")
                        requested_ids = command.get("alert_ids")
                        if not isinstance(requested_ids, Sequence) or isinstance(requested_ids, (str, bytes)):
                            return {"status": "invalid", "reason": "alert_ids_must_be_an_array", "execution_allowed": False}
                        current_alerts = {item.alert_id: item for item in alerts}
                        selected_ids = tuple(sorted({str(item).strip() for item in requested_ids if str(item).strip()}))
                        if not selected_ids or any(identifier not in current_alerts for identifier in selected_ids):
                            return {"status": "invalid", "reason": "alert_condition_not_active_for_selected_snapshot", "execution_allowed": False}
                        snoozed_until = None
                        if command_type == "snooze":
                            snoozed_until = _portfolio_goals_action_time(command.get("until"))
                            if datetime.fromisoformat(snoozed_until) <= datetime.fromisoformat(saved_at):
                                return {"status": "invalid", "reason": "snooze_until_must_follow_action_time", "execution_allowed": False}
                        for identifier in selected_ids:
                            acknowledgement_history.append({
                                "alert_id": identifier,
                                "source_snapshot_hash": current_hash,
                                "action": command_type,
                                "acted_at": saved_at,
                                "snoozed_until": snoozed_until,
                            })
                    else:
                        return {"status": "invalid", "reason": "unsupported_portfolio_goals_action", "execution_allowed": False}

                    state = {
                        "schema_version": PORTFOLIO_GOALS_SCHEMA,
                        "policy_versions": versions,
                        "scenarios": scenarios,
                        "acknowledgement_history": acknowledgement_history,
                    }
                    store.put(entity_type, storage_id, state, expected_revision=stored_revision)
    except ValueError as exc:
        return {"status": "invalid", "reason": str(exc), "execution_allowed": False}
    except StorageRevisionConflict as exc:
        return {"status": "conflict", "reason": str(exc), "execution_allowed": False}
    except (OSError, sqlite3.Error, StorageSchemaError) as exc:
        return _portfolio_goals_unavailable(f"local_portfolio_goals_store_unavailable:{type(exc).__name__}")

    versions = state.get("policy_versions", [])
    versions = versions if isinstance(versions, list) else []
    active_record = versions[-1] if versions else None
    latest_policy = policy_from_record(active_record)
    effective_policy = _portfolio_goals_policy_as_of(versions, analysis)
    policy_id = f"portfolio-goals:{storage_id}"
    editor_value = policy_editor_value(latest_policy)
    current_hash = source_snapshot_hash(analysis) if analysis is not None else None
    alert_policy = effective_policy or PortfolioPolicy(policy_id=policy_id, version=0)
    effective_policy_binding = _portfolio_goals_policy_binding(
        latest_policy or PortfolioPolicy(policy_id=policy_id, version=0)
    )
    evidence = _portfolio_goals_evidence(snapshot, analysis, alert_policy, command_type) if analysis is not None else {}
    if analysis is not None:
        alerts, unavailable_alerts = build_alerts(
            analysis,
            alert_policy,
            snapshot=snapshot,
            evidence=evidence,
            snapshot_hash=current_hash,
        )
    else:
        alerts, unavailable_alerts = (), ({"kind": "all", "status": "unavailable", "reason": "analysis_unavailable"},)
    actions = state.get("acknowledgement_history", [])
    actions = actions if isinstance(actions, list) else []
    decorated_alerts: list[dict[str, object]] = []
    for alert in alerts:
        history = [
            row for row in actions
            if isinstance(row, Mapping)
            and row.get("alert_id") == alert.alert_id
            and row.get("source_snapshot_hash") == current_hash
        ]
        snoozes = [row for row in history if row.get("action") == "snooze"]
        decorated_alerts.append({
            **alert_record(alert),
            "acknowledged": any(row.get("action") == "acknowledge" for row in history),
            "snoozed_until": snoozes[-1].get("snoozed_until") if snoozes else None,
        })
    scenario_history = state.get("scenarios", [])
    scenario_history = scenario_history if isinstance(scenario_history, list) else []
    latest_scenario = scenario_history[-1] if scenario_history else {
        "status": "unavailable", "reason": "no_what_if_scenario_has_been_run", "execution_allowed": False,
    }
    return {
        "status": "available" if latest_policy is not None or not versions else "unavailable",
        "reason": None if latest_policy is not None or not versions else "stored_portfolio_policy_invalid",
        "source_snapshot_hash": current_hash,
        "policy": None if latest_policy is None else policy_record(latest_policy),
        "policy_as_of": (
            {"status": "available", "version": effective_policy.version, "policy_id": effective_policy.policy_id}
            if effective_policy is not None
            else {"status": "unavailable", "reason": "no_policy_version_available_at_source_decision_time" if versions else "no_saved_policy"}
        ),
        "effective_policy_binding": effective_policy_binding,
        "policy_editor": editor_value,
        "policy_history": versions,
        "alerts": decorated_alerts,
        "unavailable_alerts": list(unavailable_alerts),
        "acknowledgement_history": actions,
        "scenario": latest_scenario,
        "scenarios": scenario_history,
        "audit_export": {
            "policy_versions": versions,
            "scenario_results": scenario_history,
            "alerts": decorated_alerts,
            "acknowledgements": actions,
        },
        "execution_allowed": False,
    }


def _portfolio_goals_evidence(
    snapshot: object,
    analysis: PortfolioAnalysis | None,
    policy: PortfolioPolicy,
    action_type: str,
) -> dict[str, object]:
    if analysis is None:
        return {}
    evidence: dict[str, object] = {}
    service_evidence = getattr(analysis, "service_evidence", {})
    service_evidence = service_evidence if isinstance(service_evidence, Mapping) else {}
    risk = service_evidence.get("risk")
    risk = risk if isinstance(risk, Mapping) else {}
    for metric in ("max_drawdown", "income_yield", "liquidity_eur", "forecast_deterioration"):
        value = risk.get(metric) if metric == "max_drawdown" else service_evidence.get(metric)
        if metric == "max_drawdown" and not isinstance(value, Mapping):
            portfolio_risk = risk.get("portfolio")
            if isinstance(portfolio_risk, Mapping) and metric in portfolio_risk:
                value = {
                    "status": risk.get("status", "unavailable"),
                    "value": portfolio_risk.get(metric),
                    "reason": risk.get("reason"),
                }
        evidence[metric] = value if isinstance(value, Mapping) else {
            "status": "unavailable",
            "value": None,
            "reason": f"canonical_{metric}_projection_unavailable",
        }
    needs_calendar = action_type == "simulate" or any((
        policy.event_within_days is not None,
        policy.maturity_within_days is not None,
        policy.maximum_maturity_days is not None,
    ))
    if needs_calendar:
        try:
            evidence["calendar"] = load_portfolio_calendar_projection(snapshot, analysis)
        except (OSError, KeyError, TypeError, ValueError, AttributeError):
            evidence["calendar"] = {"status": "unavailable", "reason": "point_in_time_calendar_unavailable", "events": None}
    return evidence


def _portfolio_goals_action_time(value: object) -> str:
    raw = datetime.now(timezone.utc) if value is None else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if raw.tzinfo is None:
        raise ValueError("portfolio goal action times must include a timezone")
    return raw.astimezone(timezone.utc).isoformat()


def _portfolio_goals_policy_as_of(versions: Sequence[object], analysis: object | None) -> PortfolioPolicy | None:
    binding = getattr(analysis, "snapshot_binding", None) if analysis is not None else None
    raw_cutoff = str(getattr(binding, "as_of", "") or "").strip()
    if not raw_cutoff:
        return None
    try:
        if len(raw_cutoff) == 10:
            cutoff = datetime.combine(date.fromisoformat(raw_cutoff), datetime.max.time(), tzinfo=timezone.utc)
        else:
            cutoff = datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                return None
            cutoff = cutoff.astimezone(timezone.utc)
    except ValueError:
        return None
    for record in reversed(versions):
        if not isinstance(record, Mapping):
            continue
        try:
            saved_at = datetime.fromisoformat(str(record.get("saved_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if saved_at.tzinfo is None or saved_at.astimezone(timezone.utc) > cutoff:
            continue
        policy = policy_from_record(record)
        if policy is not None:
            return policy
    return None


def _portfolio_goals_policy_binding(policy: PortfolioPolicy) -> dict[str, object]:
    record = policy_record(policy)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return {
        "policy_id": policy.policy_id,
        "version": policy.version,
        "policy_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }


def _validate_portfolio_goal_identifiers(policy: PortfolioPolicy, snapshot: object) -> None:
    config = getattr(snapshot, "config", None)
    universe = getattr(config, "universe", None)
    by_id = getattr(universe, "by_id", None)
    if not callable(by_id):
        raise ValueError("portfolio policy instrument universe is unavailable")
    valid_ids = {str(value) for value in by_id()}
    holdings = getattr(snapshot, "holdings", None)
    if isinstance(holdings, pd.DataFrame):
        column = "etf_id" if "etf_id" in holdings.columns else "instrument_id" if "instrument_id" in holdings.columns else None
        if column is not None:
            valid_ids.update(str(value).strip() for value in holdings[column].tolist() if str(value).strip())
    policy_ids = {key for key, _ in policy.target_weights} | {key for key, _, _ in policy.target_bands}
    unknown = sorted(policy_ids - valid_ids)
    if unknown:
        raise ValueError(f"unknown portfolio policy instrument ids: {', '.join(unknown)}")


def _portfolio_goals_unavailable(reason: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "reason": reason,
        "policy": {"status": "unavailable", "value": None, "reason": reason},
        "policy_history": [],
        "alerts": [],
        "unavailable_alerts": [{"kind": "all", "status": "unavailable", "reason": reason}],
        "acknowledgement_history": [],
        "scenario": {"status": "unavailable", "reason": reason, "execution_allowed": False},
        "execution_allowed": False,
    }
