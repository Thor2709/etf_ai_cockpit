"""Score authority (#941): one versioned lineage per visible score; forecasts separate from rank; penalties display-only."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import instrument_detail_view as detail
from etf_cockpit.application import score_views
from etf_cockpit.application import scoreboard_publication as publication
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.contracts import ScoreViewModel
from etf_cockpit.data import score_history, trust_artifacts
from etf_cockpit.signals import simple_scores as ss
from etf_cockpit.signals.canonical_scoring import FORECAST_DOMAIN, load_score_policy, rank_domain_weights

FORECAST_KEYS = {"baseline", "timesfm", "toto"}
_COVERAGE: dict[str, float] = {}


def _row(display_id: str, final: float | None, *, rank: int | None = None, coverage: float = 1.0, **extra) -> ss.SimpleInstrumentScore:
    _COVERAGE[display_id] = coverage
    return ss.SimpleInstrumentScore(
        instrument_key=f"etf:{display_id}",
        display_id=display_id,
        source_group="primary",
        asset_type="ETF",
        name=display_id,
        yahoo_symbol=display_id,
        latest_date=extra.pop("latest_date", "2026-10-09"),
        latest_price=extra.pop("latest_price", 10.0),
        final_score_10=final,
        decision="x",
        one_line_reason="Base.",
        components=[],
        warnings=[],
        evidence_score_10=final,
        rank=rank,
        score_rank=rank,
        **extra,
    )


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(score_views, "_CACHE", {})
    # Coverage is derived from components in production; the tests pin it per instrument.
    monkeypatch.setattr(ss.SimpleInstrumentScore, "score_coverage", property(lambda self: _COVERAGE.get(self.display_id, 1.0)))


def _patch_scores(monkeypatch, rows):
    monkeypatch.setattr(score_views, "build_simple_instrument_scores", lambda *a, **k: list(rows))


def _snapshot(signals=()):
    return SimpleNamespace(signals=tuple(signals), universe_revision="r1", forecasts=pd.DataFrame(), prices=pd.DataFrame(), config=None)


# --- the four issue tests ---------------------------------------------------------------------------------------


def test_every_visible_score_field_has_a_lineage_row() -> None:
    frame = ss.simple_scoreboard_frame([replace(_row("AAA", 7.0, rank=1), components=[])])
    surfaces = {
        "scoreboard": list(frame.columns),
        "history": list(trust_artifacts.SCORE_HISTORY_COLUMNS),
        "ui": [*score_views.score_card_values(_row("AAA", 7.0)), *score_views.score_display_values(_row("AAA", 7.0))],
        "api": list(ScoreViewModel.model_fields),
    }
    for surface, fields in surfaces.items():
        assert publication.unregistered_score_fields(fields, surface) == [], surface
    assert publication.unregistered_score_fields(score_history._COLUMNS) == []
    # a component family column is covered by the pattern row; an unknown score column fails
    assert publication.unregistered_score_fields(["momentum_score_10", "mystery_score_10"]) == ["mystery_score_10"]
    assert publication.unregistered_score_fields(["not_a_score"]) == []

    manifest = publication.score_lineage_manifest()
    assert manifest and all(row["schema_version"] == publication.LINEAGE_SCHEMA_VERSION for row in manifest)
    assert {row["authority"] for row in manifest} <= set(publication.AUTHORITIES)
    assert {row["surface"] for row in manifest} <= set(publication.SCORE_SURFACES)
    for row in manifest:
        for key in ("origin_formula", "code_path", "config_hash", "data_cutoff", "eligibility_rule", "horizon"):
            assert row[key], (row["field"], key)
        assert row["execution_allowed"] is False
    v3 = next(row for row in manifest if row["field"] == "canonical_attractiveness_10")
    assert v3["config_hash"] == load_score_policy("ETF").formula_checksum
    rank = publication.score_rank_authority()
    assert rank["candidate_rank_path"] == "DA-v1" and rank["cutover_gate"] == "#811"
    assert rank["active_rank_path"] in {"legacy_composite", "DA-v1"} and rank["execution_allowed"] is False


def test_rank_authority_and_manifest_agree_before_and_after_the_cutover(monkeypatch) -> None:
    from etf_cockpit.analysis.decision import rank_validation as rv

    def rank_rows(manifest):
        return [row for row in manifest if row["authority"] == "rank"]

    off = publication.score_rank_authority()
    assert off["active_rank_path"] == "legacy_composite" and off["cutover_active"] is False
    assert "legacy_composite" not in off["display_only_paths"]
    display_only_code = [off["path_code"][path] for path in off["display_only_paths"]]
    rows = rank_rows(publication.score_lineage_manifest())
    assert {row["field"] for row in rows} >= {"final_combined_score_10", "rank", "score", "research_score_10"}
    for row in rows:
        assert not any(code in row["code_path"] for code in display_only_code), (row["field"], row["code_path"])
        assert off["path_code"][off["active_rank_path"]] in row["code_path"], row["field"]

    active = rv.RankCutover(True, True, "QVM", "v3", {"record_id": "r"}, "promoted_rank_active")
    monkeypatch.setattr(rv, "resolve_rank_cutover", lambda **kwargs: active)
    on = publication.score_rank_authority()
    assert on["active_rank_path"] == "DA-v1" and on["active_ranker"] == "QVM" and "legacy_composite" in on["display_only_paths"]
    on_code = [on["path_code"][path] for path in on["display_only_paths"]]
    for row in rank_rows(publication.score_lineage_manifest()):
        assert not any(code in row["code_path"] for code in on_code), (row["field"], row["code_path"])
    assert not rank_rows(publication.score_lineage_manifest()), "after the cutover the legacy composite carries no rank authority"


def test_da_v1_and_qv_qvm_scores_are_registered_beside_v3_and_legacy() -> None:
    from dataclasses import fields as dataclass_fields

    from etf_cockpit.analysis.decision.contracts import OpportunityBenchmarkRank, OpportunityResult

    decision_fields = [
        *(item.name for item in dataclass_fields(OpportunityResult)),
        *(f"benchmark_rankers.{item.name}" for item in dataclass_fields(OpportunityBenchmarkRank)),
        "active_rank_score", "v3_replay_score",  # the cutover route attached by application/decision_views.py
    ]
    assert publication.unregistered_score_fields(decision_fields, "decision") == []
    # real component columns (not just the pattern) on the persisted surfaces
    component_columns = [f"{key}_score_10" for key in ss.COMPONENT_LABELS]
    for surface in ("ui", "scoreboard", "history"):
        assert publication.unregistered_score_fields(component_columns, surface) == [], surface
    assert publication.unregistered_score_fields(["benchmark_rankers.mystery", "mystery_rank_score_10"], "decision") == ["mystery_rank_score_10"]

    manifest = publication.score_lineage_manifest()
    decision_rows = [row for row in manifest if row["surface"] == "decision"]
    assert decision_rows and {row["authority"] for row in decision_rows} == {"decision"}
    assert all(row["execution_allowed"] is False for row in decision_rows)
    benchmark = next(row for row in decision_rows if row["field"] == "benchmark_rankers.score")
    assert {"QV", "QVM"} <= set(benchmark["active_weights"]) and "QVM" in benchmark["origin_formula"]
    assert benchmark["formula_version"] and benchmark["config_hash"] not in {"none", ""}
    # side by side: all paths appear in one manifest, and the cutover state is explicit
    assert {row["weights_source"] for row in manifest} >= {
        "signals/simple_scores.py:ETF_EVIDENCE_WEIGHTS|STOCK_EVIDENCE_WEIGHTS", "configs/score_engine_v3.yaml",
        "configs/decision_cutover_v1.yaml",
    }
    assert "cutover_active" in publication.score_rank_authority()


def test_same_instrument_and_date_share_one_value_across_ui_export_scoreboard_history_api(monkeypatch, tmp_path) -> None:
    rows = [_row("AAA", 8.2, rank=1, coverage=0.5), _row("BBB", 6.1, rank=2)]
    _patch_scores(monkeypatch, rows)
    monkeypatch.setattr(score_views, "missing_data_penalty", lambda: True)  # display penalty on must not leak
    snapshot = _snapshot()
    published = score_views.published_scores(snapshot)
    scoreboard_path = tmp_path / "scoreboard.parquet"
    ss.write_simple_scoreboard(published, scoreboard_path)
    monkeypatch.setattr(trust_artifacts, "SCORE_HISTORY_PATH", tmp_path / "score_history.parquet")
    history_path = trust_artifacts.append_score_history(
        published, run_id="r1", created_at="2026-10-09T10:00:00Z", version_registry_signature="sig", dependency_graph_hash="dep"
    )
    api_rows = {item.instrument_id: item for item in LocalApplicationApi(lambda: snapshot).get_scores().items}
    board = pd.read_parquet(scoreboard_path).set_index("instrument_id")
    export = pd.read_csv(scoreboard_path.with_suffix(".csv")).set_index("instrument_id")
    history = pd.read_parquet(history_path).set_index("instrument_id")
    shown = {item.display_id: item for item in score_views.snapshot_scores(snapshot, penalise_missing=True)}
    for row in rows:
        expected = row.final_score_10
        ui = next(item for item in score_views.snapshot_scores(snapshot, penalise_missing=False) if item.display_id == row.display_id)
        assert ui.final_score_10 == expected
        # the field actually shown with the preference on: UI final_score_10 is the display-adjusted value, and the
        # research score beside it is the single stored value every other surface carries
        values = score_views.score_display_values(shown[row.display_id])
        assert values["research_score_10"] == expected
        assert shown[row.display_id].final_score_10 == values["display_adjusted_score_10"]
        assert values["display_adjusted_score_10"] == round(5.0 + (expected - 5.0) * _COVERAGE[row.display_id], 2)
        assert board.loc[row.display_id, "final_combined_score_10"] == expected
        assert export.loc[row.display_id, "final_combined_score_10"] == expected
        assert history.loc[row.display_id, "final_combined_score_10"] == expected
        assert api_rows[row.display_id].score == expected
        assert history.loc[row.display_id, "rank"] == row.rank
    ui_row = publication.lineage_row_for("final_score_10", "ui")
    assert ui_row is not None and ui_row.authority == "descriptive" and "display_adjusted_score_10" in ui_row.origin_formula
    assert publication.lineage_row_for("final_score_10", "history") is None  # the UI label is never stored under that name


def test_forecast_domain_weight_in_the_rank_is_zero_unless_promoted() -> None:
    for weights in (ss.ETF_EVIDENCE_WEIGHTS, ss.STOCK_EVIDENCE_WEIGHTS):
        assert {key: weights[key] for key in FORECAST_KEYS} == {key: 0.0 for key in FORECAST_KEYS}
    for asset in ("ETF", "STOCK"):
        policy = load_score_policy(asset)
        assert FORECAST_KEYS.isdisjoint(policy.groups["attractiveness"]) and FORECAST_KEYS.isdisjoint(policy.groups["risk_implementation"])
        assert rank_domain_weights(policy)[FORECAST_DOMAIN] == 0.0
        # an incomplete or malformed promotion never moves the weight
        for record in (None, {}, {"promoted": True}, {"promoted": True, "test_id": "928", "weight": float("nan")},
                       {"promoted": True, "test_id": "928", "weight": 1.5}, {"promoted": False, "test_id": "928", "weight": 0.2}):
            assert rank_domain_weights(policy, forecast_promotion=record)[FORECAST_DOMAIN] == 0.0
        assert rank_domain_weights(policy, forecast_promotion={"promoted": True, "test_id": "928", "weight": 0.2})[FORECAST_DOMAIN] == 0.2
    forecast_rows = [row for row in publication.score_lineage_manifest() if row["domain"] == FORECAST_DOMAIN]
    assert forecast_rows and all(row["rank_weight"] == 0.0 and row["authority"] == "descriptive" for row in forecast_rows)
    assert publication.score_rank_authority()["domain_rank_weights"][FORECAST_DOMAIN] == 0.0
    # S3-02: no v3 row implies forecast weights as active rank weights
    v3_rows = [row for row in publication.score_lineage_manifest() if row["weights_source"] == "configs/score_engine_v3.yaml"]
    assert v3_rows
    for row in v3_rows:
        if row["domain"] == FORECAST_DOMAIN:
            assert set(row["active_weights"]) == {"domain_internal_sizing_not_rank_weights"}
        else:
            assert set(row["active_weights"]) == {"attractiveness", "risk_implementation"}
            assert FORECAST_DOMAIN not in row["active_weights"]
            assert all(FORECAST_KEYS.isdisjoint(group) for group in row["active_weights"].values())


def test_historical_score_row_is_unchanged_after_a_formula_version_bump(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(trust_artifacts, "SCORE_HISTORY_PATH", tmp_path / "score_history.parquet")

    def canonical(version: str) -> SimpleNamespace:
        return SimpleNamespace(
            attractiveness_10=7.0, expected_return_10=None, risk_implementation_10=6.0, evidence_confidence_10=5.0,
            coverage=0.9, formula_version=version, formula_checksum=f"sum-{version}", source_vintage_hash=f"vin-{version}",
        )

    first = replace(_row("AAA", 7.0, rank=1), canonical_score=canonical("score-engine-v3.0.0"))
    path = trust_artifacts.append_score_history(
        [first], run_id="run-1", created_at="2026-10-09T10:00:00Z", version_registry_signature="s", dependency_graph_hash="d"
    )
    before = pd.read_parquet(path).set_index("run_id").loc[["run-1"]]
    bumped = replace(_row("AAA", 4.0, rank=1), canonical_score=canonical("score-engine-v3.1.0"))
    trust_artifacts.append_score_history(
        [bumped], run_id="run-2", created_at="2026-10-10T10:00:00Z", version_registry_signature="s2", dependency_graph_hash="d2"
    )
    after = pd.read_parquet(path)
    assert set(after["run_id"]) == {"run-1", "run-2"}
    pd.testing.assert_frame_equal(before, after.set_index("run_id").loc[["run-1"]])
    assert after.set_index("run_id").loc["run-1", "formula_version"] == "score-engine-v3.0.0"
    assert after.set_index("run_id").loc["run-2", "formula_version"] == "score-engine-v3.1.0"


# --- bughunt entries (one native test each; a passing test on the base means REJECTED) --------------------------


def test_c015_n001_typed_api_uses_canonical_0_10_and_keeps_score_only_rows(monkeypatch) -> None:
    _patch_scores(monkeypatch, [_row("ETF1", 7.0, rank=1), _row("ONLY", 3.5, rank=2)])
    signal = SimpleNamespace(etf_id="ETF1", signal_date="2026-10-09", total_score=0.75, research_state="manual_review", confidence=0.8, status="ok")
    items = {item.instrument_id: item for item in LocalApplicationApi(lambda: _snapshot([signal])).get_scores().items}
    assert items["ETF1"].score == 7.0  # not the raw signal 0.75 on [-1, 1]
    assert "ONLY" in items and items["ONLY"].score == 3.5
    assert all(item.score is None or 0.0 <= item.score <= 10.0 for item in items.values())


def test_c015_n001_signal_without_score_row_never_exposes_the_raw_signal_value(monkeypatch) -> None:
    _patch_scores(monkeypatch, [])
    signal = SimpleNamespace(etf_id="SIG", signal_date="2026-10-09", total_score=0.75, research_state="manual_review", confidence=0.8, status="ok")
    (item,) = LocalApplicationApi(lambda: _snapshot([signal])).get_scores().items
    assert item.instrument_id == "SIG" and item.score is None and item.state == "manual_review"


class _Session:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.score_history_warning = None

    @contextmanager
    def activity_publication(self, expected_action_id=None):
        yield

    def _record_score_history_failure(self, exc, path):
        raise AssertionError(f"unexpected history failure: {exc!r}")


def test_c015_n002_display_penalty_is_never_persisted_to_scoreboard_or_history(monkeypatch, tmp_path) -> None:
    _patch_scores(monkeypatch, [_row("AAA", 9.0, rank=1, coverage=0.2)])
    monkeypatch.setattr(score_views, "missing_data_penalty", lambda: True)
    stored: dict[str, list] = {}
    history_stub = tmp_path / "score_history.parquet"
    history_stub.write_bytes(b"stub")
    for name, value in {
        "load_latest_candidate_report": lambda: (None, None),
        "context_from_snapshot": lambda *a, **k: SimpleNamespace(benchmark_data_id="B", projection=None, registry=None),
        "build_market_regime": lambda *a, **k: object(),
        "write_market_regime": lambda _r: None,
        "load_forecast_history": lambda: None,
        "evaluate_forecast_calibration": lambda *a: object(),
        "write_forecast_calibration": lambda _c: None,
        "simple_scoreboard_frame": lambda scores: stored.setdefault("frame", list(scores)) and pd.DataFrame(),
        "write_simple_scoreboard": lambda scores: stored.setdefault("scoreboard", list(scores)) and (tmp_path / "s.parquet"),
        "write_trust_artifacts_for_scores": lambda config, scores, frame, prices=None: (
            stored.setdefault("trust", list(scores)) and {"score_history": history_stub}
        ),
        "_record_scoreboard_publication_binding": lambda *a, **k: {},
    }.items():
        monkeypatch.setattr(publication, name, value)
    publication._write_current_scoreboard(_Session(_snapshot()))
    for key in ("scoreboard", "trust"):
        assert [item.final_score_10 for item in stored[key]] == [9.0], key
    displayed = score_views.snapshot_scores(_snapshot())
    assert displayed[0].final_score_10 == 5.0 + (9.0 - 5.0) * 0.2  # the penalty stays a display value


def test_e107_n002_b021_n003_visible_rank_follows_the_displayed_score(monkeypatch) -> None:
    rows = [_row("AAA", 9.0, rank=1, coverage=0.2), _row("BBB", 7.0, rank=2, coverage=1.0), _row("CCC", None, rank=3)]
    _patch_scores(monkeypatch, rows)
    penalised = score_views.snapshot_scores(_snapshot(), penalise_missing=True)
    by_id = {row.display_id: row for row in penalised}
    assert by_id["AAA"].final_score_10 == 5.8 and by_id["BBB"].final_score_10 == 7.0
    assert [by_id[name].rank for name in ("BBB", "AAA", "CCC")] == [1, 2, 3]
    assert all(row.rank == row.score_rank for row in penalised)
    ordered = sorted((r for r in penalised if r.final_score_10 is not None), key=lambda r: r.rank)
    assert [r.final_score_10 for r in ordered] == sorted((r.final_score_10 for r in ordered), reverse=True)
    stored = {row.display_id: row.rank for row in score_views.published_scores(_snapshot())}
    assert stored == {"AAA": 1, "BBB": 2, "CCC": 3}  # stored research rank is untouched


def test_e107_n002_b021_n003_rank_delta_uses_the_displayed_basis_with_the_penalty_on(monkeypatch) -> None:
    rows = [_row("AAA", 9.0, rank=1, coverage=0.2), _row("BBB", 6.0, rank=2, coverage=1.0)]
    _patch_scores(monkeypatch, rows)
    scores = score_views.snapshot_scores(_snapshot(), penalise_missing=True)
    visible = {row.display_id: row.rank for row in scores}
    assert visible == {"AAA": 2, "BBB": 1}  # 9.0 at 20% coverage displays as 5.8, below BBB
    # unchanged previous run: stored (unpenalised) ranks are AAA 1 / BBB 2 in both runs
    history = pd.DataFrame([
        {"run_id": "prev", "instrument_id": "AAA", "final_combined_score_10": 9.0, "coverage": 0.2, "rank": 1},
        {"run_id": "prev", "instrument_id": "BBB", "final_combined_score_10": 6.0, "coverage": 1.0, "rank": 2},
        {"run_id": "cur", "instrument_id": "AAA", "final_combined_score_10": 9.0, "coverage": 0.2, "rank": 1},
        {"run_id": "cur", "instrument_id": "BBB", "final_combined_score_10": 6.0, "coverage": 1.0, "rank": 2},
    ])
    stored = {"AAA": (1.0, 1.0), "BBB": (2.0, 2.0)}
    info = score_views.displayed_rank_info(stored, scores, history, "prev")
    assert info == {"AAA": (2, 2), "BBB": (1, 1)}  # previous recomputed with the same penalty; nothing moved
    deltas = {key: old - new for key, (old, new) in info.items()}
    assert deltas == {"AAA": 0, "BBB": 0}
    assert all(info[key][1] == visible[key] for key in info)  # the delta's current rank is the visible rank
    # penalty off: the stored pair is returned unchanged; an unknown previous run gives no delta
    plain = score_views.snapshot_scores(_snapshot(), penalise_missing=False)
    assert score_views.displayed_rank_info(stored, plain, history, "prev") == stored
    assert score_views.displayed_rank_info(stored, scores, history, "missing-run") == {"AAA": (None, 2), "BBB": (None, 1)}


def test_c015_n003_late_backfill_does_not_become_latest_or_invert_the_delta() -> None:
    def run(run_id: str, evidence: str, completed: str, score: float) -> dict:
        return {"run_id": run_id, "instrument_id": "AAA", "data_as_of_date": evidence, "run_completed_at": completed,
                "final_combined_score_10": score, "run_started_at": completed, "snapshot_hash": run_id}

    history = pd.DataFrame([
        run("r1", "2026-10-08", "2026-10-09T10:00:00Z", 5.0),
        run("r2", "2026-10-12", "2026-10-12T10:00:00Z", 7.0),
        run("r3-backfill", "2026-10-01", "2026-10-13T10:00:00Z", 3.0),  # completes last, evidence is oldest
    ])
    ordered = score_views.evidence_ordered_history(history)
    assert list(ordered["run_id"]) == ["r3-backfill", "r1", "r2"]
    panel = detail._history_panel("AAA", history)
    assert panel["rows"][-1]["run_id"] == "r2"
    changes = detail._run_changes_panel("AAA", history)
    assert changes["status"] == "available"  # the unavailable/exception path must fail this test
    assert changes["current_run_id"] == "r2" and changes["previous_run_id"] == "r1"
    (change,) = changes["changes"]
    assert change["instrument_id"] == "AAA" and change["score_delta"] == 2.0  # 7.0 - 5.0; the backfill never enters


LIVE_VINTAGE = "a" * 64  # score panels only surface sha256-shaped vintages
OLD_VINTAGE = "b" * 64


def _live_canonical(vintage: str) -> SimpleNamespace:
    return SimpleNamespace(
        source_vintage_hash=vintage, formula_checksum="f1", attractiveness_10=7.5, expected_return_10=None,
        risk_implementation_10=6.5, evidence_confidence_10=0.8, coverage=1.0, formula_version="v3",
    )


def test_c115_n001_stale_stored_scoreboard_never_supplies_evidence_beside_the_live_headline(monkeypatch, tmp_path) -> None:
    import etf_cockpit.application.instrument_detail_view as view
    from etf_cockpit.application.snapshot_builder import build_snapshot

    live = _row("AAA", 7.0, canonical_score=_live_canonical(LIVE_VINTAGE))
    fresh = {"source_vintage_hash": LIVE_VINTAGE, "formula_checksum": "f1"}
    assert detail._scoreboard_matches_live(fresh, live) is True
    assert detail._scoreboard_matches_live({**fresh, "source_vintage_hash": OLD_VINTAGE}, live) is False
    assert detail._scoreboard_matches_live({"formula_checksum": "f1"}, live) is False  # unverifiable is stale
    assert detail._scoreboard_matches_live({**fresh, "formula_checksum": "f0"}, live) is False

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    live = replace(live, display_id=instrument_id, instrument_key=f"etf:{instrument_id}", final_label="Live label")
    stored = {
        "display_id": instrument_id, "evidence_score_10": 3.0, "evidence_quality_10": 3.5, "final_label": "Stale label",
        "one_line_reason": "Stored.", "freshness_status": "ok", "formula_checksum": "f1",
    }

    def evidence(vintage: str) -> dict:
        path = tmp_path / f"scoreboard-{vintage}.parquet"
        pd.DataFrame([{**stored, "source_vintage_hash": vintage}]).to_parquet(path, index=False)
        monkeypatch.setattr(view, "SCOREBOARD_PATH", path)
        panel = view.build_instrument_detail(snapshot, instrument_id, live_score=live).sections["scores"]
        return {key: panel[key] for key in ("evidence_score", "evidence_quality", "final_label", "source_vintage_hash")}

    # a stale stored row (other vintage) is replaced wholesale by the live row's evidence
    assert evidence(OLD_VINTAGE) == {
        "evidence_score": 7.0, "evidence_quality": live.evidence_quality_10, "final_label": "Live label", "source_vintage_hash": LIVE_VINTAGE,
    }
    # a stored row from the same vintage is kept untouched
    assert evidence(LIVE_VINTAGE) == {
        "evidence_score": 3.0, "evidence_quality": 3.5, "final_label": "Stale label", "source_vintage_hash": LIVE_VINTAGE,
    }


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"latest_price": 10.0, "latest_date": "2026-10-09"}, "ok"),
        ({"latest_price": 0.0, "latest_date": "2026-10-09"}, "invalid"),
        ({"latest_price": None, "latest_date": "2026-10-09"}, "invalid"),
        ({"latest_price": 10.0, "latest_date": "2026-09-01"}, "stale"),
        ({"latest_price": 10.0, "latest_date": "2026-12-31"}, "invalid"),  # dated after the run: look-ahead
        ({"latest_price": 10.0, "latest_date": "not a date"}, "invalid"),
        ({"latest_price": None, "latest_date": "2026-10-09", "final_label": "scorecard_owned"}, "ok"),  # native bank row: no price
    ],
)
def test_e101_n002_invalid_or_stale_price_rows_are_never_marked_ok(kwargs, expected) -> None:
    fresh_component = SimpleNamespace(freshness_status="ok")
    score = replace(_row("AAA", 7.0, **kwargs), components=[fresh_component])
    assert trust_artifacts._score_freshness(score, "2026-10-10T00:00:00Z") == expected


def test_e101_n004_same_date_duplicate_scores_do_not_depend_on_row_order(monkeypatch, tmp_path, caplog) -> None:
    def signal(total: float) -> SimpleNamespace:
        return SimpleNamespace(etf_id="AAA", signal_date="2026-10-09", total_score=total, research_state="s", confidence=0.5, status="ok")

    for order in ((signal(0.2), signal(0.9)), (signal(0.9), signal(0.2))):
        chosen, conflict = score_views.latest_signal_per_instrument(order)["AAA"]
        assert conflict is True and chosen.total_score == 0.2
        _patch_scores(monkeypatch, [])
        monkeypatch.setattr(score_views, "_CACHE", {})
        (item,) = LocalApplicationApi(lambda order=order: _snapshot(order)).get_scores().items
        assert item.score is None and item.status == "conflicting_same_date_signals"
    identical = score_views.latest_signal_per_instrument((signal(0.5), signal(0.5)))["AAA"]
    assert identical[1] is False

    # persisted history: conflicting duplicates are not stored by "last row wins"; identical ones collapse
    monkeypatch.setattr(trust_artifacts, "SCORE_HISTORY_PATH", tmp_path / "score_history.parquet")
    for index, scores in enumerate(([_row("AAA", 7.0), _row("AAA", 4.0), _row("BBB", 6.0)], [_row("BBB", 6.0), _row("AAA", 4.0), _row("AAA", 7.0)])):
        path = trust_artifacts.append_score_history(
            scores, run_id=f"run-{index}", created_at="2026-10-09T10:00:00Z", version_registry_signature="s", dependency_graph_hash="d"
        )
        stored = pd.read_parquet(path)
        stored = stored.loc[stored["run_id"] == f"run-{index}"]
        assert list(stored["instrument_id"]) == ["BBB"]
        assert list(stored["rank"]) == [1] and list(stored["score_rank"]) == [1]  # dropped duplicates never hold a rank slot
    collapsed = trust_artifacts._unique_scores_by_instrument([_row("AAA", 7.0), _row("AAA", 7.0)])
    assert len(collapsed) == 1
    caplog.clear()
    with caplog.at_level("WARNING", logger=trust_artifacts.__name__):
        trust_artifacts._unique_scores_by_instrument([_row("AAA", 7.0), _row("AAA", 4.0)])
    assert any("AAA" in record.getMessage() and "conflicting" in record.getMessage() for record in caplog.records)
