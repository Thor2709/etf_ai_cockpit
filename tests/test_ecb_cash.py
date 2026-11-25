"""E1: ECB overnight cash rates (EONIA before 2019-10-01, €STR from it) and the rank-validation cash table."""

from __future__ import annotations

from datetime import date, datetime, timezone
import importlib.util
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.ecb_cash import fetch_overnight_rates, forward_cash_returns, parse_ecb_rate_csv, splice_overnight_rates
from tests.test_gap_811 import _load_runner, _price_table, _write_inputs

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ecb_cash"
_FETCHED = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)


def _sample(source: str) -> bytes:
    return (_FIXTURES / f"{source}_sample.csv").read_bytes()


def _parsed(source: str) -> pd.DataFrame:
    return parse_ecb_rate_csv(_sample(source), source=source, fetched_at=_FETCHED)


def test_parser_reads_both_samples_skips_blanks_and_records_the_publication_basis() -> None:
    blank = _sample("estr") + b"EST.B.EU000A2X2A25.WT,B,EU000A2X2A25,WT,2026-11-24,,M\n"
    estr = parse_ecb_rate_csv(blank, source="estr", fetched_at=_FETCHED)
    eonia = _parsed("eonia")
    assert len(estr) == 10 and len(eonia) == 10 and "2026-11-24" not in estr["rate_date"].astype(str).tolist()
    friday = estr.loc[estr["rate_date"].eq(date(2026, 11, 13))].iloc[0]
    assert friday["rate_pct"] == 2.437 and friday["source"] == "estr"
    assert friday["available_at"] == pd.Timestamp("2026-11-16T07:00Z")  # next TARGET day 08:00 CET
    assert friday["availability_basis"] == "estr_next_target_day_publication"
    assert estr.iloc[-1]["availability_basis"] == "live_ingestion" and estr.iloc[-1]["available_at"] == pd.Timestamp(_FETCHED)
    assert eonia.iloc[0]["available_at"] == pd.Timestamp("2019-09-25T17:00Z")  # same day 19:00 CEST
    with pytest.raises(ValueError):
        parse_ecb_rate_csv(_sample("eonia"), source="estr", fetched_at=_FETCHED)


def test_splice_uses_eonia_before_2019_10_01_and_estr_from_it() -> None:
    estr_2019 = _parsed("eonia").assign(source="estr")  # stand-in €STR rows on the split days
    spliced = splice_overnight_rates(_parsed("eonia"), estr_2019)
    by_day = dict(zip(spliced["rate_date"].astype(str), spliced["source"]))
    assert by_day["2019-09-30"] == "eonia" and by_day["2019-10-01"] == "estr" and len(spliced) == 10


def test_cash_return_compounds_act_360_and_fails_closed_on_a_gap() -> None:
    rates = _parsed("estr")
    sessions = [date(2026, 11, day) for day in (12, 13, 16, 17, 18, 19, 20, 23)]
    table = forward_cash_returns(rates, sessions, 2).set_index("decision_date")
    thursday = (1 + 0.02443 / 360) * (1 + 0.02437 * 3 / 360) - 1  # 11-12 -> 11-16: Thu 1 day, Fri 3 days
    assert table.loc["2026-11-12", "net_return"] == pytest.approx(thursday, rel=1e-12)
    assert table.loc["2026-11-12", "source"] == "estr"
    assert "2026-11-19" in table.index and "2026-11-20" not in table.index  # 11-20 has no two later sessions
    gapped = rates.loc[~rates["rate_date"].isin([date(2026, 11, day) for day in (16, 17, 18)])]
    without = forward_cash_returns(gapped, sessions, 2)["decision_date"].tolist()
    assert "2026-11-12" not in without and "2026-11-13" not in without and "2026-11-19" in without
    stopped = forward_cash_returns(rates.loc[rates["rate_date"].lt(date(2026, 11, 20))], sessions, 2)
    assert stopped["decision_date"].tolist()[-1] == "2026-11-17"  # 11-18 ends 11-20, after the last rate day 11-19


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "ecb_cash_rates.py"
    spec = importlib.util.spec_from_file_location("ecb_cash_rates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_writes_rates_and_manifest_and_the_cash_table_fills_rank_validation(tmp_path: Path) -> None:
    from etf_cockpit.data.provenance import sha256_dataframe

    estr = "".join(
        f"EST.B.EU000A2X2A25.WT,{day.date().isoformat()},3.0\n" for day in pd.bdate_range("2022-12-01", "2025-06-30")
    )
    payloads = {"EON": _sample("eonia"), "EST": f"KEY,TIME_PERIOD,OBS_VALUE\n{estr}".encode()}
    root = tmp_path / "root"
    written = fetch_overnight_rates(root, transport=lambda url: payloads[url.split("/data/")[1][:3]])
    stored = pd.read_parquet(written)
    manifest = json.loads(written.with_suffix(".json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == sha256_dataframe(stored)
    assert stored["source"].value_counts().to_dict() == {"estr": len(stored) - 4, "eonia": 4}

    prices = _price_table(520)
    base = _write_inputs(tmp_path, prices)
    (root / "data" / "validated" / "prices").mkdir(parents=True)
    prices.to_parquet(root / "data" / "validated" / "prices" / "prices_daily.parquet")
    cash = tmp_path / "cash.csv"
    assert _script().main(["table", "--root", str(root), "--out", str(cash)]) == 0

    def cash_means(arguments: list[str]) -> list[object]:
        out = tmp_path / "report.json"
        assert _load_runner().main([*arguments, "--years", "1", "--out", str(out)]) == 0
        return re.findall(r'"cash_net_mean": ([^,}]+)', out.read_text(encoding="utf-8"))

    without = [item for index, item in enumerate(base) if item != "--cash" and base[index - 1] != "--cash"]
    assert set(cash_means(without)) == {"null"}
    filled = cash_means(base)
    assert filled and all(0.002 < float(item) < 0.003 for item in filled)  # 3 % a year over ~30 days
