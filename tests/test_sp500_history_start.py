"""D9: the generated S&P 500 run config can start at an earlier fja snapshot (1996 instead of the 2021-10-01 default)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import yaml

from scripts import acquire_sp500 as acq


def test_the_config_step_takes_an_explicit_history_start(monkeypatch, tmp_path):
    from etf_cockpit.data import universe_store

    layout = acq.Layout(tmp_path)
    manifest = {"files": {name: {"fetched_at": "2026-11-02T00:00:00+00:00"} for name in (
        "fja_history.csv", "company_tickers.json", "wikipedia_changes.html", "wikipedia_constituents.html")},
        "fja_commit": "a" * 40, "licence_ref": "synthetic"}
    (layout.sources / "manifest.json").write_text(json.dumps(manifest))
    (layout.raw / "resolve.json").write_text(json.dumps({"members": {}, "ciks": {}}))
    monkeypatch.setattr(universe_store, "load_universe", lambda _: SimpleNamespace(integrity_errors=[], records=[], revision=1))
    snapshots = [{"date": "1996-01-02", "tickers": ["ZZZ"]}, {"date": "2021-09-30", "tickers": ["YYY"]}]
    monkeypatch.setattr(acq, "load_history", lambda _: {"snapshots": snapshots, "wiki_events": [],
                                                     "fja_events": acq.fja_events(snapshots), "current": []})

    assert acq.main(["--root", str(tmp_path), "--step", "config", "--history-start", "1996-01-02"]) == 0

    for name in ("run_config.yaml", "run_config_block.yaml"):
        config = yaml.safe_load((layout.raw / name).read_text())
        assert config["history_start"] == "1996-01-02"
        assert "dated snapshot 1996-01-02" in config["baseline_source"]
