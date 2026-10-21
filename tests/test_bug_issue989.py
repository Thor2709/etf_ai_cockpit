"""Issue #989 V8 intake: export-pack as-of filter, horizon labels and evidence-tree symlink containment."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.chatgpt_bridge import export_pack


def test_latest_features_exclude_rows_after_as_of_date() -> None:
    features = pd.DataFrame(
        {
            "etf_id": ["A", "A", "A", "B"],
            "date": ["2026-01-02", "2026-01-05", "2026-01-09", "2026-01-12"],
            "momentum_20d": [1.0, 2.0, 99.0, 98.0],
        }
    )
    known = export_pack._features_known_by(features, date(2026, 1, 6))
    latest = known.sort_values("date").groupby("etf_id").tail(1)
    assert latest.set_index("etf_id")["momentum_20d"].to_dict() == {"A": 2.0}
    assert export_pack._features_known_by(features, date(2025, 1, 1)).empty


def test_horizon_score_columns_never_carry_non_horizon_values() -> None:
    signal = SimpleNamespace(
        etf_id="A",
        to_v2_dict=lambda: {},
        canonical_score=None,
        confidence=0.5,
        total_score=0.7,
        supporting_metrics={},
        reason_long="r",
        reason_short="r",
        blocked_by=[],
        components=SimpleNamespace(momentum=0.9, trend=0.8, baseline_ml=0.6),
    )
    rows = export_pack._signal_rows([signal], SimpleNamespace(universe=SimpleNamespace(etfs=[])))
    for column in ("score_1w", "score_1m", "score_3m", "score_6m", "score_9m"):
        assert rows[0][column] is None


def test_copy_evidence_tree_does_not_read_through_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "ok.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("owner secret", encoding="utf-8")
    try:
        os.symlink(outside, root / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    destination = tmp_path / "packet" / "evidence_export" / "run_manifests"
    manifest: dict[str, object] = {}
    export_pack._copy_evidence_tree(root, destination, manifest)
    copied = [path for path in (tmp_path / "packet").rglob("*") if path.is_file()]
    assert all("owner secret" not in path.read_text(encoding="utf-8") for path in copied)
    assert (destination / "ok.json").exists() and not (destination / "link.txt").exists()
    markers = [path for path in copied if path.name.endswith("_unsafe_link.txt")]
    assert markers and json.loads(markers[0].read_text(encoding="utf-8"))["reason"] == "symlink_outside_evidence_root"


def test_copy_evidence_tree_skips_entries_reported_as_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "ok.json").write_text("{}", encoding="utf-8")
    (root / "linked.txt").write_text("owner secret", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "linked.txt" or original(self))
    destination = tmp_path / "packet" / "evidence_export" / "run_manifests"
    export_pack._copy_evidence_tree(root, destination, {})
    assert (destination / "ok.json").exists() and not (destination / "linked.txt").exists()
