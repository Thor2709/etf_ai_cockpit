from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from etf_cockpit.audit.thesis_diary import ThesisDiaryIntegrityError


def test_s13_08_local_audit_refuses_remote_endpoint(monkeypatch):
    import etf_cockpit.audit.local_llm as llm

    get, post = Mock(), Mock()
    get.return_value.json.return_value = {"data": [{"id": "fixture-model"}]}
    post.return_value.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"summary": "fixture", "confidence": 0.5, "executable_authority": False}
                    )
                }
            }
        ]
    }
    monkeypatch.setattr(llm.requests, "get", get)
    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setenv("ETF_COCKPIT_OFFLINE", "1")
    settings = llm.LocalLLMSettings(base_url="http://198.51.100.1/v1")
    context = {"signals": [{"etf_id": "VWCE", "reason_full": "private review evidence"}]}

    llm.generate_local_audit_commentary(context, settings)

    assert not post.called


def test_s13_09_future_snapshot_cannot_grant_historical_authority():
    from etf_cockpit.data.score_history import score_history_v2_payload
    from etf_cockpit.governance.migrations import migrate_legacy_action

    row = {
        "schema_version": "1.0",
        "action": "hold",
        "final_action": "hold",
        "as_of_date": "2020-01-02",
        "data_as_of_date": "2020-01-02",
        "run_completed_at": "2020-01-02T23:59:59+00:00",
        "portfolio_snapshot": {
            "as_of_date": "2026-10-06",
            "portfolio_review_state": "reduce_exposure_review",
            "holdings": [{"instrument_id": "VWCE", "weight": 0.5}],
        },
    }

    assert not migrate_legacy_action(row).portfolio_review_allowed
    assert not score_history_v2_payload(row)["portfolio_review_allowed"]


def test_s13_10_export_does_not_invent_model_forecasts(monkeypatch):
    import etf_cockpit.chatgpt_bridge.export_pack as ep
    from etf_cockpit.core.types import ComponentScores, SignalResult

    config = SimpleNamespace(
        universe=SimpleNamespace(etfs=[]),
        targets=SimpleNamespace(base_currency="EUR"),
        risks=SimpleNamespace(portfolio_limits=SimpleNamespace(model_dump=lambda: {})),
    )
    signal = SignalResult(
        run_id="fixture",
        signal_date=date(2026, 8, 3),
        etf_id="VWCE",
        action="hold",
        confidence=0.5,
        total_score=0.1,
        components=ComponentScores(*([0.0] * 12)),
        blocked_by=[],
        warnings=[],
        reason_short="review",
        reason_long="review",
        horizon_primary="1-3 months",
        supporting_metrics={
            "momentum_60d": 0.2,
            "q50_expected_return": -0.05,
            "expected_return_horizon_days": 20,
        },
        model_versions_used={"baseline": "momentum_shrunk_v1", "timesfm": "timesfm_2_5_optional"},
    )
    captured = []

    class StopExport(Exception):
        pass

    def capture(frame, path, **kwargs):
        if Path(path).name == "04_model_forecasts.csv":
            captured.append(frame.copy())
            raise StopExport

    monkeypatch.setattr(pd.DataFrame, "to_csv", capture)
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(Path, "write_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(ep, "allocation_frame", lambda *args, **kwargs: [])
    monkeypatch.setattr(ep, "_audit_portfolio_holdings", lambda *args, **kwargs: [])
    with pytest.raises(StopExport):
        ep.export_review_pack(
            config,
            pd.DataFrame({"market_value_eur": [100], "current_weight": [0.5]}),
            pd.DataFrame({"date": [date(2026, 8, 3)], "etf_id": ["VWCE"]}),
            [signal],
            None,
            as_of_date=date(2026, 8, 3),
        )

    assert captured[0]["status"].eq("unavailable").all()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S13-11: Malformed security findings silently clear release blockers",
)
def test_s13_11_malformed_findings_fail_closed(tmp_path):
    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.security.policy import build_security_report

    configs = tmp_path / "configs"
    configs.mkdir()
    for name in ("security_policy.yaml", "plugin_registry.yaml"):
        (configs / name).write_bytes((ROOT / "configs" / name).read_bytes())
    path = tmp_path / "artifacts" / "security" / "findings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"id": "CVE-fixture", "severity": "critical", "status": "open"}),
        encoding="utf-8",
    )

    assert build_security_report(tmp_path)["status"] == "failed"


def test_s13_12_from_imported_broker_sdk_is_rejected(tmp_path):
    from etf_cockpit.governance.static_checks import run_static_execution_boundary_check

    path = tmp_path / "src" / "etf_cockpit" / "adapters" / "analysis_client.py"
    path.parent.mkdir(parents=True)
    path.write_text("from ib_insync import IB\n", encoding="utf-8")

    report = run_static_execution_boundary_check(tmp_path)

    assert any(v.code == "PROHIBITED_BROKER_DEPENDENCY" for v in report.violations)


def test_s13_13_unapproved_unsigned_intake_blocks(monkeypatch, tmp_path):
    from copy import deepcopy

    from etf_cockpit.core.paths import ROOT
    import etf_cockpit.governance.supply_chain_intake as sc
    from scripts import check_supply_chain_intake as cli

    registry = deepcopy(sc.load_supply_chain_intake(ROOT / "configs" / "supply_chain_intake.yaml"))
    registry["review_status"] = "approved"
    registry["components"] = registry["components"][:1]
    registry["components"][0].update(
        licence="MIT",
        licence_class="permissive",
        copied_files=[],
        review_status="hardening_required",
    )
    registry["signature"]["path"] = str(tmp_path / "missing.sig.json")
    monkeypatch.setattr(sc, "load_supply_chain_intake", lambda *args: registry)
    monkeypatch.setattr(
        sc,
        "_locked_dependencies",
        lambda *args: ({"package": "fixture", "licence": "MIT", "repository": "fixture", "maintainer": "fixture"},),
    )
    monkeypatch.setattr(sc, "_tracked_external_paths", lambda *args: ())
    monkeypatch.setattr(cli, "write_supply_chain_intake_report", lambda *args: None)

    assert cli.main(["--root", str(ROOT)]) != 0


def test_s13_14_native_smoke_checks_requested_executable(monkeypatch):
    from scripts import smoke_app as smoke

    monkeypatch.setattr(smoke, "verify_ui_action_inventory", lambda: None)
    monkeypatch.setattr(smoke, "verify_expected_title", lambda: None)
    monkeypatch.setattr(smoke, "_verify_score_groups", lambda: None)
    monkeypatch.setattr(smoke, "_fetch_root", lambda url: None)
    monkeypatch.setattr(
        smoke.launcher_core,
        "choose_launch_port",
        lambda host, port, allow_reuse: SimpleNamespace(
            port=port, requested_port=port, reason="reused", reuse_existing=True
        ),
    )
    monkeypatch.setattr(
        smoke.launcher_core,
        "wait_for_ready",
        lambda *args: SimpleNamespace(ready=True, url="http://127.0.0.1:8550", message="ready"),
    )

    def missing_native(*args, **kwargs):
        raise RuntimeError("missing native executable")

    monkeypatch.setattr(smoke.launcher_core, "_launch_command", missing_native)

    assert smoke.main(["--mode", "native", "--port", "8550", "--timeout", "1"]) != 0


def test_s13_15_redacted_forward_only_packet_replays(tmp_path):
    from etf_cockpit.audit.thesis_diary import (
        ThesisDiaryStore,
        build_thesis_entry,
        reproduce_thesis_from_packet,
    )

    store = ThesisDiaryStore(tmp_path)
    entry = build_thesis_entry(
        prompt="Review",
        model="local",
        source_snapshot={},
        retrieval_snapshot={},
        evidence_snapshot={
            "backtest_metadata": {"forward_only": True, "llm_available_at_decision": True}
        },
        llm_output={"summary": "review"},
        backtest_validity="forward_only",
        decision_time="2026-08-03T00:00:00+00:00",
        thesis_id="forward-1",
    )
    store.create(entry)
    store.append_redaction(
        entry.thesis_id,
        state="redacted",
        reason="private",
        decision_time="2026-08-03T01:00:00+00:00",
    )
    packet = store.export_packet(disclosure_safe=True, at="2026-08-03T02:00:00+00:00")

    state = reproduce_thesis_from_packet(packet, entry.thesis_id, at="2026-08-03T02:00:00+00:00")

    assert state.entry.content_redacted is True
