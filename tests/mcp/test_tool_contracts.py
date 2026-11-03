"""Required-arguments-only contracts over the existing offline flow root.

The isolated driver seeds once and calls every read-tier declaration, including
full-profile tools. Parametrised assertions report each tool independently.
Missing fixture evidence may fail closed; omitted optional arguments must not
produce INVALID_ARGUMENTS. Exactly-one-of tools receive one documented alternative.
Sizes include the same envelope as the stdio server.
"""

from __future__ import annotations

from datetime import date
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from etf_cockpit.mcp.registry import list_tools


READ_TOOLS = list_tools(profile="full", tiers="read")
REQUIRED_ARGUMENTS = {
    "alert_update_preview": {"alert_id": "missing", "action": "dismiss", "expected_revision": 1},
    "backtest_get": {"cost_regime": "default"},
    "compare_instruments": {"ids": ["VWCE", "FIXTURE1"]},
    "data_readiness": {"start": date(2026, 10, 29), "end": date(2026, 10, 30)},
    "etf_disclosures": {"instrument_id": "VWCE"},
    "etf_economics": {"instrument_id": "VWCE"},
    "etf_holdings": {"instrument_id": "VWCE", "as_of": date(2026, 10, 30)},
    "etf_overlap": {"instrument_ids": ["VWCE"]},
    "forecast_get": {"instrument_ids": ["VWCE"], "horizons": [21]},
    "forecast_lab_compare": {"horizon": 21},
    "identity_get": {"instrument_id": "VWCE"},
    "instrument_detail": {"instrument_id": "VWCE"},
    "instrument_lookup": {"identifier": "VWCE.DE"},
    "job_cancel": {"job_id": "missing", "reason": "contract fixture"},
    "job_status": {"job_id": "missing"},
    "monthly_decision_pack": {"month": "2026-10"},
    "paper_portfolio": {"account_id": "l9-paper"},
    "portfolio_candidate_analyse": {"target_weights": {"VWCE": 1.0}},
    "research_record_thesis_preview": {
        "instrument_ids": ["VWCE"], "thesis": "Fixture claim", "evidence_refs": [],
        "invalidation_rules": ["Review evidence"], "review_date": "2026-11-30",
    },
    "score_explain": {"instrument_id": "VWCE"},
    "score_history": {"instrument_id": "VWCE"},
    "settings_change_preview": {"changes": {}},
}
DOCUMENTED_ALTERNATIVES = {"audit_validate": {"text": "{}"}}


@pytest.fixture(scope="module")
def read_responses(tmp_path_factory):
    fixture_dir = Path(__file__).parent / "fixtures"
    root = tmp_path_factory.mktemp("read-contract") / "root"
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "universe.yaml").write_bytes((fixture_dir / "universe.yaml").read_bytes())
    env = {**os.environ, "ETF_COCKPIT_ROOT": str(root), "CUDA_VISIBLE_DEVICES": "",
           "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(root)],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(line for line in completed.stdout.splitlines() if line.startswith("CONTRACT_RESULTS="))
    return json.loads(line.removeprefix("CONTRACT_RESULTS="))


@pytest.mark.parametrize("spec", READ_TOOLS, ids=lambda spec: spec.name)
def test_read_tool_required_arguments_contract(spec, read_responses):
    arguments = REQUIRED_ARGUMENTS.get(spec.name, {})
    required = {name for name, parameter in inspect.signature(spec.function).parameters.items()
                if parameter.default is inspect.Parameter.empty}
    assert set(arguments) == required, "Update the small required-argument table; optional arguments must stay omitted"
    response = read_responses[spec.name]
    assert response["reason_code"] != "INVALID_ARGUMENTS", response
    assert response["reason_code"] != "UNEXPECTED_EXCEPTION", response
    assert response["json_chars"] <= 32_000, response


def _drive(root):
    sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
    from run_flows import context, seed

    from etf_cockpit.mcp.errors import MCPToolError
    from etf_cockpit.mcp.registry import invoke_tool
    from etf_cockpit.mcp.serialise import build_envelope, envelope_dict

    seed(root, 0)
    active = context(root)
    results = {}
    for spec in READ_TOOLS:
        reason = None
        try:
            value = invoke_tool(spec.name, {**REQUIRED_ARGUMENTS.get(spec.name, {}), **DOCUMENTED_ALTERNATIVES.get(spec.name, {})}, context=active)
            response = envelope_dict(build_envelope(value))
        except MCPToolError as exc:
            reason = exc.reason_code
            response = {"error": str(exc)}
        except Exception as exc:
            reason = "UNEXPECTED_EXCEPTION"
            response = {"error": f"{type(exc).__name__}: {exc}"}
        encoded = json.dumps(response, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        results[spec.name] = {"reason_code": reason, "json_chars": len(encoded),
                              "error": response.get("error")}
    print("CONTRACT_RESULTS=" + json.dumps(results))


if __name__ == "__main__":
    _drive(Path(sys.argv[1]).resolve())
