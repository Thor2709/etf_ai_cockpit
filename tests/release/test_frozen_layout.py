from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "etf_cockpit"


def test_spec_bundles_all_package_data() -> None:
    spec_path = ROOT / "ETF_AI_Cockpit.spec"
    spec = spec_path.read_text(encoding="utf-8")
    tree = ast.parse(spec)
    package_data_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "collect_data_files"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "etf_cockpit"
    ]

    assert "from PyInstaller.utils.hooks import collect_data_files" in spec
    assert package_data_calls
    assert any(
        any(
            keyword.arg == "include_py_files"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in call.keywords
        )
        for call in package_data_calls
    )
    package_data = [path for path in PACKAGE_ROOT.rglob("*") if path.is_file() and path.suffix != ".py"]
    assert package_data
    assert "collect_data_files('etf_cockpit', include_py_files=False)" in spec


def test_no_module_derives_configs_from_file_parents() -> None:
    config_parent = re.compile(
        r"Path\s*\(\s*__file__\s*\)[\s\S]{0,120}?parents\s*\[\s*\d+\s*\][\s\S]{0,120}?[\"']configs[\"']"
    )
    hits = []
    for source_path in PACKAGE_ROOT.rglob("*.py"):
        if source_path.relative_to(PACKAGE_ROOT).as_posix() == "parsers/contracts.py":
            continue
        source = source_path.read_text(encoding="utf-8")
        if config_parent.search(source):
            hits.append(source_path.relative_to(ROOT).as_posix())
    assert not hits, f"module-derived configs paths remain: {hits}"


def test_frozen_layout_resolves_configs_from_release_root(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    internal_root = release_root / "ETF_AI_Cockpit" / "_internal"
    package_destination = internal_root / "etf_cockpit"
    shutil.copytree(PACKAGE_ROOT, package_destination)
    shutil.copytree(ROOT / "configs", release_root / "configs")
    outside = tmp_path / "outside"
    outside.mkdir()

    script = """
from pathlib import Path
from etf_cockpit.application.analysis_depth import ANALYSIS_DEPTH_PROFILES_PATH, load_analysis_depth_profiles
from etf_cockpit.analysis.fund_analysis import FUND_ANALYSIS_CONFIG, load_fund_analysis_config
from etf_cockpit.analysis.decision.opportunity import _DEFAULT_CONFIG, load_opportunity_policy

root = Path(__import__('os').environ['ETF_COCKPIT_ROOT']).resolve()
assert ANALYSIS_DEPTH_PROFILES_PATH == root / 'configs' / 'analysis_depth_profiles.yaml'
assert FUND_ANALYSIS_CONFIG == root / 'configs' / 'fund_analysis_v1.yaml'
assert _DEFAULT_CONFIG == root / 'configs' / 'decision_opportunity_v1.yaml'
assert load_analysis_depth_profiles()
assert load_fund_analysis_config()
assert load_opportunity_policy()
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(internal_root)
    environment["ETF_COCKPIT_ROOT"] = str(release_root)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
