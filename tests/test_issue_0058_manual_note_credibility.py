from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages.data_models import data_models_page
from etf_cockpit.app.pages.instrument_detail import render_news_context_panel
from etf_cockpit.app.pages import chatgpt_audit, trust_evidence
from etf_cockpit.app.selectors import instrument_detail
from etf_cockpit.app.selectors.instrument_detail import InstrumentDetailViewModel
from etf_cockpit.data.manual_notes import (
    CREDIBILITY_FLAG_CODES,
    CREDIBILITY_FLAG_COLUMNS,
    CREDIBILITY_SCHEMA_VERSION,
    load_manual_news,
    manual_news_markdown,
    validate_manual_news,
)


def _text_values(node: object) -> list[str]:
    values: list[str] = []
    value = getattr(node, "value", None)
    if value:
        values.append(str(value))
    for attribute in ("controls", "content"):
        children = getattr(node, attribute, None)
        if isinstance(children, (list, tuple)):
            for child in children:
                values.extend(_text_values(child))
        elif children is not None:
            values.extend(_text_values(children))
    for row in getattr(node, "rows", []) or []:
        for cell in getattr(row, "cells", []) or []:
            values.extend(_text_values(getattr(cell, "content", None)))
    return values


def _classified_frame(note: str) -> pd.DataFrame:
    result = validate_manual_news(
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-08-01",
                    "etf_id": "TEST-ETF",
                    "title": "Manual credibility fixture",
                    "note": note,
                    "source": "manual_test",
                }
            ]
        )
    )
    assert result.ok, result.errors
    return result.frame


def test_issue_0058_classifier_persists_all_structured_reason_codes() -> None:
    frame = _classified_frame(
        "Performance screenshot shows +500% return. No methodology, benchmark, drawdown, costs, "
        "slippage, sample size, or reproducible method. DM me for the closed-source black box."
    )
    row = frame.iloc[0]

    assert row["credibility_schema_version"] == CREDIBILITY_SCHEMA_VERSION
    assert row["credibility_flag_status"] == "available"
    assert set(row["credibility_flags"].split("|")) == set(CREDIBILITY_FLAG_CODES)
    assert row["credibility_reason_codes"] == row["credibility_flags"]
    assert all(row[column] == "detected" for column in CREDIBILITY_FLAG_COLUMNS)
    assert bool(row["executable_authority"]) is False


def test_issue_0058_classifier_distinguishes_present_evidence_and_negation() -> None:
    complete = _classified_frame(
        "The performance screenshot shows a 20% return versus its benchmark. Methodology, "
        "reproducible source code, n=100 trades, drawdown 8%, fees and slippage are disclosed."
    ).iloc[0]
    negated = _classified_frame(
        "No screenshot, not a funnel, open source code, and no performance claim."
    ).iloc[0]
    mixed = _classified_frame(
        "No screenshot, but the performance screenshot shows a 20% return with methodology."
    ).iloc[0]

    assert all(complete[column] == "not_detected" for column in CREDIBILITY_FLAG_COLUMNS)
    assert all(negated[column] == "not_detected" for column in CREDIBILITY_FLAG_COLUMNS)
    assert mixed["credibility_flag_performance_screenshot_without_methodology"] == "not_detected"


def test_issue_0058_source_metadata_cannot_satisfy_claim_evidence() -> None:
    note = "Performance screenshot shows +500% return."
    control = _classified_frame(note).iloc[0]
    result = validate_manual_news(
        pd.DataFrame(
            [{
                "as_of_date": "2026-08-01",
                "title": "Claim",
                "note": note,
                "source_url": "https://example.invalid/methodology/benchmark/drawdown/costs/sample-size",
            }]
        )
    )
    assert result.ok
    enriched = result.frame.iloc[0]

    assert enriched["credibility_flags"] == control["credibility_flags"]
    assert enriched["credibility_evidence"] == control["credibility_evidence"]


def test_issue_0058_no_missing_wording_does_not_invert_into_missing_flags() -> None:
    row = _classified_frame(
        "Performance screenshot shows a 20% return. The review found no missing benchmark, "
        "drawdown, costs, sample size, or methodology."
    ).iloc[0]

    for code in (
        "missing_benchmark",
        "missing_drawdown",
        "missing_cost_slippage",
        "missing_sample_size",
        "missing_reproducible_method",
    ):
        assert row[f"credibility_flag_{code}"] == "not_detected"


def test_issue_0058_legacy_frame_loads_with_explicit_unknown_structured_truth(tmp_path) -> None:
    path = tmp_path / "legacy_manual_news.parquet"
    pd.DataFrame(
        [{"as_of_date": "2026-08-01", "etf_id": "TEST-ETF", "title": "Legacy", "note": "Old note"}]
    ).to_parquet(path, index=False)

    loaded = load_manual_news(path)

    assert loaded.iloc[0]["credibility_flag_status"] == "unavailable"
    assert loaded.iloc[0]["credibility_flags"] == "unknown"
    assert all(loaded.iloc[0][column] == "unknown" for column in CREDIBILITY_FLAG_COLUMNS)


def test_issue_0058_malformed_structured_frame_fails_closed(tmp_path) -> None:
    path = tmp_path / "malformed_manual_news.parquet"
    frame = _classified_frame("Performance screenshot shows +500% return without methodology.")
    frame.loc[0, "credibility_flags"] = "none"
    frame.to_parquet(path, index=False)

    loaded = load_manual_news(path)

    assert loaded.iloc[0]["credibility_schema_version"] == "unknown"
    assert loaded.iloc[0]["credibility_flag_status"] == "unavailable"
    assert loaded.iloc[0]["credibility_flags"] == "unknown"


def test_issue_0058_coherently_tampered_structured_frame_fails_closed(tmp_path) -> None:
    path = tmp_path / "tampered_manual_news.parquet"
    frame = _classified_frame("Performance screenshot shows +500% return; closed-source black box.")
    frame.loc[0, "credibility_flags"] = "none"
    frame.loc[0, "credibility_reason_codes"] = "none"
    frame.loc[0, "credibility_evidence"] = "{" + ",".join(
        f'"{code}":"not_detected"' for code in CREDIBILITY_FLAG_CODES
    ) + "}"
    for column in CREDIBILITY_FLAG_COLUMNS:
        frame.loc[0, column] = "not_detected"
    frame.to_parquet(path, index=False)

    loaded = load_manual_news(path)

    assert loaded.iloc[0]["credibility_flag_status"] == "unavailable"
    assert loaded.iloc[0]["credibility_flags"] == "unknown"


def test_issue_0058_audit_markdown_exposes_flags_and_non_executable_authority() -> None:
    frame = _classified_frame("+500% return screenshot; DM me; no benchmark or drawdown.")

    markdown = manual_news_markdown(frame)

    assert "credibility_flags=" in markdown
    assert "too_good_to_be_true_return_claim" in markdown
    assert "missing_benchmark" in markdown
    assert "credibility_evidence=" in markdown
    assert "executable_authority=false" in markdown


def test_issue_0058_flags_are_context_only_and_do_not_create_score_authority() -> None:
    row = _classified_frame("Guaranteed 500% return; closed-source system.").iloc[0]

    assert bool(row["executable_authority"]) is False
    assert "score" not in row.index
    assert "action" not in row.index
    assert "execution_allowed" not in row.index


def test_issue_0058_news_context_surface_shows_structured_flags(monkeypatch) -> None:
    frame = _classified_frame("+500% return screenshot; DM me; no benchmark.")
    monkeypatch.setattr(trust_evidence, "MANUAL_NEWS_CLEAN_PATH", object())
    monkeypatch.setattr(trust_evidence, "load_manual_news", lambda _path: frame)
    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: pd.DataFrame())
    state = SimpleNamespace(snapshot=SimpleNamespace(prices=pd.DataFrame()))

    rendered = trust_evidence._news_context_extra(state)
    text = "\n".join(_text_values(rendered))

    assert "credibility_flags=" in text
    assert "missing_benchmark" in text
    assert "executable_authority=false" in text


def test_issue_0058_data_models_surface_shows_structured_flags(monkeypatch) -> None:
    frame = _classified_frame("+500% return screenshot; DM me; no benchmark.")
    monkeypatch.setattr("etf_cockpit.app.pages.data_models.load_manual_news", lambda: frame)
    monkeypatch.setattr("etf_cockpit.app.pages.data_models.build_coverage_audit", lambda *args, **kwargs: {})
    monkeypatch.setattr("etf_cockpit.app.pages.data_models.coverage_summary_lines", lambda _report: [])
    snapshot = SimpleNamespace(
        prices=pd.DataFrame({"etf_id": ["TEST-ETF"], "date": ["2026-08-01"]}),
        data_report=SimpleNamespace(status="ok", issues=[], dataset_metadata=[], as_of_date=None),
        model_status={},
        model_inventory=[],
        forecasts=pd.DataFrame(),
        signals=[],
        config=SimpleNamespace(universe=SimpleNamespace(etfs=[])),
    )

    rendered = data_models_page(None, SimpleNamespace(snapshot=snapshot, last_message=""))
    text = "\n".join(_text_values(rendered))

    assert "credibility_flags=" in text
    assert "missing_benchmark" in text
    assert "executable_authority=false" in text


def test_issue_0058_instrument_detail_surface_shows_manual_note_flags(monkeypatch) -> None:
    frame = _classified_frame("+500% return screenshot; DM me; no benchmark.")
    monkeypatch.setattr(instrument_detail, "MANUAL_NEWS_CLEAN_PATH", object())
    monkeypatch.setattr(instrument_detail, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(instrument_detail, "load_manual_news", lambda _path: frame)
    news = instrument_detail._news_panel("TEST-ETF", pd.DataFrame())
    model = InstrumentDetailViewModel("TEST-ETF", "Test ETF", "ready", {}, {"news": news})

    rendered = render_news_context_panel(model)
    text = "\n".join(_text_values(rendered))

    assert "credibility_flags=" in text
    assert "missing_benchmark" in text
    assert "executable_authority=false" in text


def test_issue_0058_audit_notes_surface_shows_manual_note_flags(monkeypatch) -> None:
    frame = _classified_frame("+500% return screenshot; DM me; no benchmark.")
    monkeypatch.setattr(chatgpt_audit, "load_manual_news", lambda: frame)
    monkeypatch.setattr(chatgpt_audit, "_thesis_diary_text", lambda: "No persisted diary entries.")
    monkeypatch.setattr(chatgpt_audit, "load_authority_matrix", lambda: SimpleNamespace(policy=None))
    monkeypatch.setattr(chatgpt_audit, "build_version_registry", lambda: object())
    monkeypatch.setattr(
        chatgpt_audit,
        "compatibility_summary",
        lambda _registry: {"record_count": 0, "registry_signature": "0" * 64},
    )
    state = SimpleNamespace(last_message="", last_export_path=None)

    rendered = chatgpt_audit.chatgpt_audit_page(SimpleNamespace(), state)
    text = "\n".join(_text_values(rendered))

    assert "Manual note credibility" in text
    assert "credibility_flags=" in text
    assert "missing_benchmark" in text
    assert "executable_authority=false" in text


def test_issue_0058_audit_notes_surface_fails_closed_on_corrupt_store(monkeypatch) -> None:
    def fail_read():
        raise ValueError("corrupt")

    monkeypatch.setattr(chatgpt_audit, "load_manual_news", fail_read)

    text = chatgpt_audit._manual_note_credibility_text()

    assert "unavailable" in text
    assert "manual review required" in text
    assert "executable_authority=false" in text
