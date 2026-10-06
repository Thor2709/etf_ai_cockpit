"""Slice S13C regression reproducers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.xfail(
    strict=True,
    raises=ValueError,
    reason="HUNT-S13C-2: Unsanitized NaN in backtest metrics aborts canonical_json serialization",
)
def test_hunt_s13c_2_nan_backtest_metric_is_normalised():
    from etf_cockpit.audit.local_llm import _normalise_context_snapshot

    context = {"backtest": {"deflated_sharpe": float("nan")}}
    snapshot = _normalise_context_snapshot(context)
    assert snapshot["backtest"]["deflated_sharpe"] is None


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="HUNT-S13C-3: Presentation boundary check bypassed by relative or top-level package imports",
)
def test_hunt_s13c_3_relative_forbidden_import_is_reported(tmp_path):
    from etf_cockpit.governance.architecture_boundaries import find_violations

    page = tmp_path / "src" / "etf_cockpit" / "app" / "pages" / "boundary_probe.py"
    page.parent.mkdir(parents=True)
    page.write_text("from ...data import store\n", encoding="utf-8")
    violations = find_violations(tmp_path)
    assert any(violation.file.endswith("boundary_probe.py") for violation in violations)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="HUNT-S13C-4: Hash digest mismatch causes duplicate unavailable markers in evidence export",
)
def test_hunt_s13c_4_missing_evidence_has_one_unavailable_marker(tmp_path, monkeypatch):
    from etf_cockpit.chatgpt_bridge import export_pack

    source_root = tmp_path / "project"
    source_root.mkdir()
    export_dir = tmp_path / "packet"
    evidence_root = export_dir / "evidence_export"
    evidence_root.mkdir(parents=True)
    missing_source = source_root / "source_conflicts.parquet"
    monkeypatch.setattr(export_pack, "ROOT", source_root)
    monkeypatch.setattr(export_pack, "GOVERNANCE_CHECKSUMS_PATH", tmp_path / "missing-policy-checksums.json")
    loader_result = SimpleNamespace(diagnostic_mode=False, policy=object(), checksum="a" * 64)
    for loader_name in (
        "load_authority_matrix",
        "load_product_governance",
        "load_feature_registry",
        "load_strategy_scope",
        "load_gate_policy",
        "load_glossary",
    ):
        monkeypatch.setattr(export_pack, loader_name, lambda result=loader_result: result)

    evidence_manifest = {"included": [], "missing": [], "checksums": {}}
    export_pack._copy_evidence_file(missing_source, evidence_root, evidence_manifest)
    export_pack._write_audit_manifest(export_dir, {}, evidence_manifest)

    markers = list(evidence_root.glob("source_conflicts_*_unavailable.txt"))
    assert len(markers) == 1


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="HUNT-S13C-5: Internal cancel_order invocations in paper_trading.py flagged as prohibited boundary",
)
def test_hunt_s13c_5_internal_cancel_order_call_is_safe(tmp_path):
    from etf_cockpit.governance.static_checks import _scan_python

    root = tmp_path
    source = root / "src" / "etf_cockpit" / "portfolio" / "paper_trading.py"
    source.parent.mkdir(parents=True)
    text = "class PaperLedger:\n    def cancel_order(self):\n        return None\n    def cancel(self):\n        self.cancel_order()\n"
    source.write_text(text, encoding="utf-8")
    violations = _scan_python(root, source, text)
    assert not any(item.code == "PROHIBITED_ORDER_SYMBOL" for item in violations)
