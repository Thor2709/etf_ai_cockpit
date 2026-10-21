"""Issue #989 (E118-N001/N004/N005): privacy export, session-log and CSV safety regressions."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from etf_cockpit.analysis.screening import ScreenQuery, bind_query, run_screen
from etf_cockpit.core import session_log
from etf_cockpit.data.privacy import export_redacted_records, redact_private_fields
from etf_cockpit.data.screen_store import export_screen_csv

_SECRET = "sk-synthetic-" + "0123456789"  # split so the supply-chain secret scan does not flag test data


def test_privacy_export_redacts_credential_assignments_in_scalar_text(tmp_path: Path) -> None:
    records = [
        {"note": f"call used api_key={_SECRET} today", "nested": ["Authorization: Bearer " + _SECRET, {"msg": f"password: {_SECRET}"}]},
    ]
    redacted = redact_private_fields(records)
    assert _SECRET not in json.dumps(redacted)
    assert redacted[0]["note"].startswith("call used api_key=")
    result = export_redacted_records(records, tmp_path / "export.json")
    assert _SECRET not in result.path.read_text(encoding="utf-8")
    assert redact_private_fields(["plain text"]) == ["plain text"]


def test_explicit_private_export_keeps_scalar_text() -> None:
    assert redact_private_fields({"note": f"api_key={_SECRET}"}, include_private=True) == {"note": f"api_key={_SECRET}"}


@dataclass
class _Holder:
    label: str
    api_key: str


class _Opaque:
    def __repr__(self) -> str:
        return f"<Opaque token={_SECRET}>"


@pytest.mark.parametrize("value", [_Holder("x", _SECRET), _Opaque(), {_Opaque()}, Path(f"/tmp/password={_SECRET}")])
def test_session_log_redacts_secrets_inside_object_reprs(tmp_path: Path, value: object) -> None:
    log = tmp_path / "session.jsonl"
    session_log.append_event({"event_type": "probe", "extra": {"payload": value, "items": [value]}}, path=log)
    text = log.read_text(encoding="utf-8")
    assert _SECRET not in text
    assert "***redacted***" in text


def test_screen_csv_export_neutralises_formula_prefixes(tmp_path: Path) -> None:
    records = [{"instrument_id": "=HYPERLINK(\"http://x\",\"y\")", "name": "+SUM(1,1)", "note": "@cmd", "other": "-1+2"}]
    query = bind_query(records, ScreenQuery(as_of=" =HYPERLINK('x')", formula_version="+SUM(1,1)"))
    result = run_screen(records, query)
    path = export_screen_csv(result, query, tmp_path / "out.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    for row in rows:
        for value in row.values():
            assert not value.lstrip().startswith(("=", "+", "-", "@")), value
    assert rows[0]["instrument_id"].endswith("HYPERLINK(\"http://x\",\"y\")")
