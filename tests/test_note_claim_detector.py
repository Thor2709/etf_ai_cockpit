from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.app.pages import trust_evidence
from etf_cockpit.data.manual_notes import (
    CREDIBILITY_FLAG_CODES,
    classify_manual_note_credibility,
    manual_news_markdown,
    record_manual_note_credibility_review,
    validate_manual_news,
)


CORPUS = json.loads(Path("tests/fixtures/notes_claim_corpus.json").read_text(encoding="utf-8"))


def _classify(text: str) -> dict[str, str]:
    return classify_manual_note_credibility(pd.Series({"title": "Corpus note", "note": text}))


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
    return values


@pytest.mark.parametrize("example", CORPUS["positives"], ids=lambda example: example["id"])
def test_each_labelled_positive_detects_its_claim(example: dict[str, str]) -> None:
    assert _classify(example["text"])[example["id"]] == "detected"


def test_clean_and_negated_corpus_examples_have_no_flags() -> None:
    for example in CORPUS["clean"]:
        evidence = _classify(example["text"])
        assert all(evidence[code] == "not_detected" for code in CREDIBILITY_FLAG_CODES), example["text"]


def test_human_review_override_is_recorded_and_precedes_display() -> None:
    validated = validate_manual_news(pd.DataFrame([{
        "as_of_date": "2026-08-01",
        "title": "Promotional return claim",
        "note": "Guaranteed +500% returns from a closed-source system.",
    }]))
    assert validated.ok
    original = validated.frame.iloc[0]["credibility_flags"]

    reviewed = record_manual_note_credibility_review(
        validated.frame,
        0,
        reviewer="analyst",
        decision="clear_flags",
        note="Reviewed source material; automated interpretation does not apply.",
        reviewed_at="2026-08-02T10:00:00+00:00",
    )
    row = reviewed.iloc[0]

    assert row["credibility_flags"] == original
    assert row["credibility_review_status"] == "reviewed"
    assert row["credibility_review_override"] == "clear_flags"
    assert row["credibility_reviewed_by"] == "analyst"
    assert row["credibility_review_note"]
    assert row["credibility_display_flags"] == "none (human review: cleared)"
    assert bool(row["executable_authority"]) is False


def test_audit_export_includes_flags_review_state_and_zero_authority() -> None:
    validated = validate_manual_news(pd.DataFrame([{
        "as_of_date": "2026-08-01",
        "title": "Promotional return claim",
        "note": "Guaranteed +500% returns from a closed-source system.",
    }]))
    reviewed = record_manual_note_credibility_review(
        validated.frame,
        0,
        reviewer="analyst",
        decision="clear_flags",
        note="Human review recorded.",
        reviewed_at="2026-08-02T10:00:00+00:00",
    )

    exported = manual_news_markdown(reviewed)

    assert "credibility_flags=" in exported
    assert "closed_source_claim" in exported
    assert "too_good_to_be_true_return_claim" in exported
    assert "display_flags=none (human review: cleared)" in exported
    assert "credibility_review_status=reviewed" in exported
    assert "credibility_review_override=clear_flags" in exported
    assert "credibility_reviewed_by=analyst" in exported
    assert "credibility_review_note=Human review recorded." in exported
    assert "executable_authority=false" in exported


def test_news_context_ui_renders_review_override_badge(monkeypatch: pytest.MonkeyPatch) -> None:
    validated = validate_manual_news(pd.DataFrame([{
        "as_of_date": "2026-08-01",
        "title": "Promotional return claim",
        "note": "Guaranteed +500% returns from a closed-source system.",
    }]))
    reviewed = record_manual_note_credibility_review(
        validated.frame,
        0,
        reviewer="analyst",
        decision="clear_flags",
        note="Human review recorded.",
        reviewed_at="2026-08-02T10:00:00+00:00",
    )
    monkeypatch.setattr(trust_evidence, "MANUAL_NEWS_CLEAN_PATH", object())
    monkeypatch.setattr(trust_evidence, "load_manual_news", lambda _path: reviewed)
    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: pd.DataFrame())
    state = SimpleNamespace(snapshot=SimpleNamespace(prices=pd.DataFrame()))

    rendered = trust_evidence._news_context_extra(state)
    text = "\n".join(_text_values(rendered))

    assert "none (human review: cleared)" in text or "clear_flags" in text
