"""Issue 971 (MR1): model registry and promotion must be evidence-bound, point-in-time and race-free."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import threading

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application.forecast_service import _stamp_promotion_states, build_forecast_lab_workspace
from etf_cockpit.core.config import ModelPromotionSettings, load_config
from etf_cockpit.features.training_centre import LocalTrainingRegistry, TrainingRegistryError
from etf_cockpit.models import registry as model_registry
from etf_cockpit.models.local_weights import LocalModelStatus
from etf_cockpit.models.model_promotion import COUNTING, NOT_PROVEN, ModelPromotion, evaluate_model_promotions
from etf_cockpit.validation.protocol import ValidationSpec, evaluate_trials
from tests.test_work_q_promotion import _days, _forecasts, _prices

MODEL_ID = "training.model"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def register_model(registry: LocalTrainingRegistry, root: Path, label: str, *, name: str | None = None) -> dict[str, object]:
    """A pending model with its own completed run and a verified artefact."""

    run_id, experiment_id = f"run-{label}", f"exp-{label}"
    registry.create_experiment(label, experiment_id=experiment_id)
    registry.create_run(
        experiment_id,
        run_id=run_id,
        dataset_hash=_hash(f"data-{label}"),
        feature_hash=_hash("features"),
        code_hash=_hash("code"),
        environment_hash=_hash("environment"),
    )
    registry.update_run(run_id, status="completed", progress=1.0)
    path = root / "models" / f"{label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{{"model":"{label}"}}', encoding="utf-8")
    artifact = registry.register_artifact(run_id, path)
    return registry.register_model(
        run_id, name=name or label, artifact_ids=[str(artifact["artifact_id"])], model_card={"method": "deterministic"}
    )


def validation_report(registry: LocalTrainingRegistry, run_id: str, *, eligible: bool = True, decide: bool = True) -> dict[str, object]:
    """Stored validation report of ``run_id`` (eligibility forced by the fixture), optionally researcher-approved."""

    values = {"baseline": np.full(20, 0.1), "challenger": np.full(20, 0.2)}
    report = evaluate_trials(values, spec=ValidationSpec(n_splits=2, test_size=5, final_test_size=5, bootstrap_repetitions=10))
    stored = registry.record_validation_report(
        run_id,
        replace(report, promotion_eligible=eligible),
        trial_returns={key: value.tolist() for key, value in values.items()},
        data_hash=_hash("data"),
        code_hash=_hash("code"),
        features={"price_basis": "adjusted_close"},
        thresholds={"minimum_score": 0.0},
        variants={"baseline": "naive", "challenger": "candidate"},
        selection_method="highest development-fold mean",
    )
    if decide and eligible:
        registry.record_researcher_decision(str(stored["report_id"]), decision="approved", reviewer="analyst", rationale="Reviewed")
    return stored


def approve_bound(registry: LocalTrainingRegistry, model: dict[str, object]) -> dict[str, object]:
    """Approve ``model`` against an eligible, researcher-approved validation report of its run."""

    report = validation_report(registry, str(model["run_id"]))
    return registry.approve_model(
        str(model["model_id"]),
        reviewer="analyst",
        evaluation={"walk_forward": "passed"},
        validation_report_id=str(report["report_id"]),
        validation_report_hash=str(report["report_fingerprint"]),
    )


def approved_model(registry: LocalTrainingRegistry, root: Path, label: str, *, name: str | None = None) -> dict[str, object]:
    return approve_bound(registry, register_model(registry, root, label, name=name))


# --- C008-N002: approval and promotion are bound to an eligible validation report ---------------------


def test_c008_n002_approval_without_an_eligible_bound_report_is_rejected(tmp_path: Path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    model = register_model(registry, tmp_path, "m1")
    other = register_model(registry, tmp_path, "m2")
    model_id, run_id = str(model["model_id"]), str(model["run_id"])
    eligible = validation_report(registry, run_id)
    foreign = validation_report(registry, str(other["run_id"]))
    good_id, good_hash = str(eligible["report_id"]), str(eligible["report_fingerprint"])
    evaluation = {"walk_forward": "passed"}

    attempts = [
        {},  # the audited defect: an arbitrary non-empty evaluation
        {"validation_report_id": good_id},  # no hash
        {"validation_report_id": "missing-report", "validation_report_hash": good_hash},
        {"validation_report_id": good_id, "validation_report_hash": _hash("tampered")},
        {"validation_report_id": str(foreign["report_id"]), "validation_report_hash": str(foreign["report_fingerprint"])},
    ]
    for kwargs in attempts:
        with pytest.raises(TrainingRegistryError):
            registry.approve_model(model_id, reviewer="analyst", evaluation=evaluation, **kwargs)
    assert registry.require(MODEL_ID, model_id)["approval_state"] == "pending"

    approved = registry.approve_model(
        model_id, reviewer="analyst", evaluation=evaluation, validation_report_id=good_id, validation_report_hash=good_hash
    )
    assert approved["validation_report_id"] == good_id and approved["validation_report_hash"] == good_hash
    assert approved["evaluation"]["validation_report_hash"] == good_hash
    assert registry.promote_model(model_id, "champion")["promotion_state"] == "champion"


def test_c008_n002_ineligible_or_unapproved_report_cannot_approve_and_unbound_approval_cannot_promote(tmp_path: Path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    ineligible_model = register_model(registry, tmp_path, "ineligible")
    ineligible = validation_report(registry, str(ineligible_model["run_id"]), eligible=False)
    unapproved_model = register_model(registry, tmp_path, "unapproved")
    unapproved = validation_report(registry, str(unapproved_model["run_id"]), decide=False)
    for model, report in ((ineligible_model, ineligible), (unapproved_model, unapproved)):
        with pytest.raises(TrainingRegistryError, match="not eligible"):
            registry.approve_model(
                str(model["model_id"]),
                reviewer="analyst",
                evaluation={"walk_forward": "passed"},
                validation_report_id=str(report["report_id"]),
                validation_report_hash=str(report["report_fingerprint"]),
            )

    # An approval recorded without a bound report (legacy evidence) cannot become champion or challenger.
    legacy = register_model(registry, tmp_path, "legacy")
    record = dict(registry.require(MODEL_ID, str(legacy["model_id"])))
    record.update({"approval_state": "approved", "promotion_state": "approved", "evaluation": {"walk_forward": "passed"}})
    registry._put(MODEL_ID, str(legacy["model_id"]), record)
    for target in ("champion", "challenger"):
        with pytest.raises(TrainingRegistryError, match="eligible validation report"):
            registry.promote_model(str(legacy["model_id"]), target, reviewer="analyst")  # type: ignore[arg-type]


# --- C008-N003 and V8 C.C3.S08.N001: availability ------------------------------------------------------


def _inventory(*names: str) -> list[LocalModelStatus]:
    return [
        LocalModelStatus(name, name, Path(name), True, 1, [], True, {}, True, "ready", "ready")
        for name in names
    ]


def _availability(monkeypatch: pytest.MonkeyPatch, registry: LocalTrainingRegistry) -> dict[str, object]:
    monkeypatch.setattr(model_registry, "model_weight_inventory", lambda _config: _inventory("timesfm", "toto"))
    return model_registry.model_availability(load_config(), training_registry=registry)


def test_c008_n003_retired_model_does_not_veto_the_active_champion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    old = approved_model(registry, tmp_path, "old", name="timesfm")
    registry.retire_model(str(old["model_id"]), reviewer="analyst", reason="superseded")
    assert _availability(monkeypatch, registry)["timesfm"] is False  # only a retired registration: still blocked

    champion = approved_model(registry, tmp_path, "new", name="timesfm")
    registry.promote_model(str(champion["model_id"]), "champion")
    availability = _availability(monkeypatch, registry)
    assert availability["timesfm"] is True and availability["reasons"]["timesfm"] is None

    # A tampered champion artefact still blocks the family.
    (tmp_path / "models" / "new.json").write_text("{}", encoding="utf-8")
    tampered = _availability(monkeypatch, registry)
    assert tampered["timesfm"] is False and tampered["reasons"]["timesfm"]


def test_c3_s08_n001_registry_failure_for_one_family_does_not_disable_the_others(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    for label in ("timesfm", "toto"):
        registry.promote_model(str(approved_model(registry, tmp_path, label)["model_id"]), "champion")
    broken = {str(item["artifact_ids"][0]) for item in registry.list_records(MODEL_ID) if item["name"] == "timesfm"}
    original = registry.verify_artifact

    def verify(artifact_id: str) -> object:
        if artifact_id in broken:
            raise OSError("artefact store unreadable")
        return original(artifact_id)

    monkeypatch.setattr(registry, "verify_artifact", verify)
    availability = _availability(monkeypatch, registry)
    assert availability["timesfm"] is False and "unavailable" in str(availability["reasons"]["timesfm"])
    assert availability["toto"] is True

    def unreadable(_entity_type: str) -> tuple[dict[str, object], ...]:
        raise OSError("roster unreadable")

    monkeypatch.setattr(registry, "list_records", unreadable)
    everything = _availability(monkeypatch, registry)
    assert everything["timesfm"] is False and everything["toto"] is False  # an unreadable roster stays fail-closed


# --- C108-N001: single champion under concurrency ------------------------------------------------------


def _champions(registry: LocalTrainingRegistry) -> list[str]:
    return sorted(str(item["model_id"]) for item in registry.list_records(MODEL_ID) if item.get("promotion_state") == "champion")


def test_c108_n001_stale_roster_cannot_create_a_second_champion(tmp_path: Path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    first = approved_model(registry, tmp_path, "first")
    second = approved_model(registry, tmp_path, "second")
    racing = LocalTrainingRegistry(tmp_path)
    original = registry.list_records
    fired: list[bool] = []

    def list_then_race(entity_type: str) -> tuple[dict[str, object], ...]:
        roster = original(entity_type)
        if entity_type == MODEL_ID and not fired:
            fired.append(True)
            racing.promote_model(str(second["model_id"]), "champion")  # lands after the first promotion read its roster
        return roster

    registry.list_records = list_then_race  # type: ignore[method-assign]
    with pytest.raises(TrainingRegistryError, match="changed concurrently"):
        registry.promote_model(str(first["model_id"]), "champion")
    assert _champions(LocalTrainingRegistry(tmp_path)) == [str(second["model_id"])]


def test_c108_n001_concurrent_promotions_leave_one_champion(tmp_path: Path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    ids = [str(approved_model(registry, tmp_path, f"m{index}")["model_id"]) for index in range(3)]
    barrier = threading.Barrier(len(ids))
    outcomes: list[object] = []

    def promote(model_id: str) -> None:
        barrier.wait()
        try:
            outcomes.append(LocalTrainingRegistry(tmp_path).promote_model(model_id, "champion"))
        except TrainingRegistryError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=promote, args=(model_id,)) for model_id in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert len(outcomes) == len(ids)
    assert any(isinstance(item, dict) for item in outcomes)
    assert len(_champions(registry)) == 1


# --- C108-N002 / C108-N003 / C022-N002: promotion evidence ---------------------------------------------


def _decide(history: pd.DataFrame, prices: pd.DataFrame, settings: ModelPromotionSettings | None = None) -> ModelPromotion:
    return evaluate_model_promotions(history, prices, prices.date.max().date(), settings or ModelPromotionSettings())["timesfm3"]


def test_c108_n002_rows_not_known_or_not_out_of_fold_at_as_of_never_count() -> None:
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": _days("2024-01-02", 30)})
    control = _decide(history, prices)
    assert control.matured_forecasts == 120 and control.counting

    late = history.assign(known_at=history["created_at"])
    backfilled = late["forecast_date"].isin(_days("2024-01-02", 30)[20:])
    late.loc[backfilled, "known_at"] = "2030-01-01T00:00:00Z"  # backfilled after the decision date
    decision = _decide(late, prices)
    assert decision.matured_forecasts == 80 and decision.forecast_origins == 20

    unknown = history.assign(known_at=pd.NaT)  # an unverifiable knowledge time fails closed
    assert _decide(unknown, prices).matured_forecasts == 0

    in_sample = history.assign(is_oof=True)
    in_sample.loc[in_sample["forecast_date"].isin(_days("2024-01-02", 30)[:10]), "is_oof"] = False
    oof = _decide(in_sample, prices)
    assert oof.matured_forecasts == 80 and oof.forecast_origins == 20

    # The same rows judged at an earlier as-of date never see later-known evidence.
    early = evaluate_model_promotions(late, prices, pd.Timestamp("2024-03-01").date(), ModelPromotionSettings())["timesfm3"]
    assert early.matured_forecasts <= decision.matured_forecasts


def test_c108_n003_floors_reject_two_pair_one_origin_configuration() -> None:
    with pytest.raises(ValueError):
        ModelPromotionSettings(minimum_matured_forecasts=2, minimum_forecast_origins=1)
    with pytest.raises(ValueError):
        ModelPromotionSettings(minimum_matured_forecasts=99)
    with pytest.raises(ValueError):
        ModelPromotionSettings(minimum_forecast_origins=4)
    raised = ModelPromotionSettings(minimum_matured_forecasts=150, minimum_forecast_origins=8)
    assert (raised.minimum_matured_forecasts, raised.minimum_forecast_origins) == (150, 8)


def test_c108_n003_limited_evidence_cannot_promote_even_when_validation_is_bypassed() -> None:
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": ["2024-01-02"]})
    history = history.loc[history.etf_id.isin(["E1", "E2"])]
    bypassed = ModelPromotionSettings.model_construct(
        enabled=True, minimum_matured_forecasts=2, minimum_forecast_origins=1, evidence_horizon_days=60
    )
    decision = _decide(history, prices, bypassed)
    assert (decision.matured_forecasts, decision.forecast_origins) == (2, 1)
    assert (decision.required_forecasts, decision.required_origins) == (100, 5)
    assert not decision.counting and decision.state == NOT_PROVEN, decision.reason


def test_c022_n002_first_local_run_is_the_generation_time_not_the_forecast_date() -> None:
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": _days("2024-01-08", 31)})
    optional = history["model_name"].eq("timesfm3")
    # The first run generated its rows on 3 January for forecast dates from 8 January onwards.
    history.loc[optional & history["forecast_date"].eq("2024-01-08"), "created_at"] = "2024-01-03T12:00:00Z"
    decision = _decide(history, prices)
    assert decision.first_local_run == "2024-01-03" and decision.evidence_after == "2024-01-03"
    # An earlier-dated row created later does not move the first run to its forecast date.
    history.loc[optional & history["forecast_date"].eq("2024-01-08"), "created_at"] = "2024-01-08T12:00:00Z"
    assert _decide(history, prices).first_local_run == "2024-01-08"


# --- C115-N002: historical Forecast Lab runs keep their run-time promotion label ------------------------


def test_c115_n002_historical_run_label_is_unchanged_by_a_later_promotion() -> None:
    config = load_config()
    prices = _prices()
    days = _days("2023-12-04", 30)
    forecasts = _forecasts(prices, {"timesfm3": days})
    forecasts["forecast_date"] = pd.to_datetime(forecasts["forecast_date"])
    # Every run stored "not_proven" when it was written; the model is promoted by today's evidence.
    forecasts["promotion_state"] = np.where(forecasts["model_name"].eq("timesfm3"), NOT_PROVEN, "reference")
    report = build_forecast_lab_workspace(config, forecasts, prices, timing_records=[])
    assert report["promotion"].set_index("model_name").loc["timesfm3", "state"] == COUNTING
    assert report["models"].set_index("model_name").loc["timesfm3", "promotion_state"] == COUNTING
    runs = report["runs"].set_index("run_id")["promotion_state"]
    assert runs.loc[f"r-{days[0]}"] == "timesfm3: not yet proven"
    assert not runs.str.contains("counting").any()

    unrecorded = _stamp_promotion_states(
        {"runs": pd.DataFrame({"run_id": ["legacy"], "models": ["timesfm3"], "promotion_state": ["shadow_only"]})},
        {"timesfm3": ModelPromotion("timesfm3", COUNTING, "today")},
        pd.DataFrame({"run_id": ["legacy"], "model_name": ["timesfm3"]}),
    )
    assert unrecorded["runs"]["promotion_state"].tolist() == ["timesfm3: not recorded at run time"]


# --- V8 intake ------------------------------------------------------------------------------------------


def test_c3_s08_n002_other_versions_rows_are_not_unverifiable_for_this_version() -> None:
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": _days("2024-01-02", 30)})
    other = history["model_name"].eq("timesfm3") & history["forecast_date"].isin(_days("2024-01-02", 30)[:4])
    history.loc[other, "model_version"] = "older"
    decision = _decide(history, prices)
    versions = {item["model_version"]: item for item in decision.version_evidence}
    assert versions["v"]["unverifiable_forecasts"] == 0 and versions["older"]["unverifiable_forecasts"] == 0
    history.loc[other & history["etf_id"].eq("E1"), "run_id"] = None  # genuinely unverifiable rows of "older"
    again = {item["model_version"]: item for item in _decide(history, prices).version_evidence}
    assert again["older"]["unverifiable_forecasts"] == 4 and again["v"]["unverifiable_forecasts"] == 0


def test_c3_s08_n003_fractional_horizon_is_not_truncated_into_the_evidence_horizon() -> None:
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": _days("2024-01-02", 30)})
    control = _decide(history, prices)
    fractional = history.copy()
    fractional["horizon_days"] = np.where(fractional["model_name"].eq("timesfm3"), 60.5, 60)
    decision = _decide(fractional, prices)
    assert control.matured_forecasts == 120
    assert decision.matured_forecasts == 0 and not decision.counting


def test_c2_s11_n001_offset_timestamp_keeps_its_local_session_date() -> None:
    from etf_cockpit.models.model_promotion import _normalised_history

    prices = _prices()
    days = _days("2024-01-02", 30)
    history = _forecasts(prices, {"timesfm3": days})
    # 20:00 at UTC-5 is 01:00 UTC on the next day, but the origin session is the written date.
    history["forecast_date"] = pd.to_datetime(history["forecast_date"]).dt.strftime("%Y-%m-%dT20:00:00-05:00")
    normalised = _normalised_history(history, pd.Timestamp(days[0]).date())
    assert set(normalised["forecast_date"]) == {pd.Timestamp(days[0])}  # known at its own session date
    assert _decide(history, prices).matured_forecasts == 120
