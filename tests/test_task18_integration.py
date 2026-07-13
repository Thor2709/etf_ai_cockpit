from __future__ import annotations

from dataclasses import replace

import pandas as pd

from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.core.config import load_config
from etf_cockpit.services import build_snapshot
from etf_cockpit.signals.simple_scores import build_simple_instrument_scores, simple_scoreboard_frame


def test_scoreboard_exports_crowding_sector_and_friction_authority_fields() -> None:
    config = load_config()
    pending = build_simple_instrument_scores(config, [], pd.DataFrame(), pd.DataFrame())[0]
    score = replace(
        pending,
        crowding_cluster_id="cluster_A_B",
        crowding_cluster_label="High correlation cluster (AI)",
        crowding_warning="high_correlation_cluster_warning",
        crowding_average_peer_correlation=0.91,
        crowding_sample_size=119,
        crowding_as_of="2026-07-10",
        sector_relative_return=0.012,
        sector_alpha_proxy=0.004,
        sector_attribution_status="available",
        friction_status="available",
        friction_reason="Informational proxy",
    )
    frame = simple_scoreboard_frame([score])

    assert frame.loc[0, "crowding_cluster_id"] == "cluster_A_B"
    assert frame.loc[0, "sector_relative_return"] == 0.012
    assert frame.loc[0, "friction_status"] == "available"
    assert bool(frame.loc[0, "execution_allowed"]) is False


def test_instrument_detail_keeps_derived_evidence_unavailable_and_non_executable(tmp_path, monkeypatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    monkeypatch.setattr(selector, "CORRELATION_CLUSTERS_PATH", tmp_path / "missing-clusters.parquet")
    monkeypatch.setattr(selector, "BENCHMARK_ATTRIBUTION_PATH", tmp_path / "missing-attribution.parquet")

    model = build_instrument_detail(snapshot, instrument_id)

    assert model.sections["scores"]["crowding"]["status"] == "unavailable"
    assert model.sections["attribution"]["sector_attribution_status"] == "N/A"
    assert model.sections["attribution"]["execution_allowed"] is False
