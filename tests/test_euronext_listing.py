from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import re

import yaml

from etf_cockpit.data import euronext_listing
from etf_cockpit.data.source_policy import load_source_policies
from etf_cockpit.data.universe_membership import capture_log, closure_events, load_raw_payload


_SCOPE = "listing:euronext_oslo:all"
_CONFIG = euronext_listing.DEFAULT_CONFIG_PATH


def test_fixture_parses_euronext_format_and_rejection_reasons() -> None:
    payload = (Path(__file__).parent / "fixtures" / "euronext_oslo_sample.csv").read_bytes()

    parsed = euronext_listing.parse_euronext_listing(payload)

    assert parsed.as_of_date == "2026-10-01"
    assert len(parsed.rows) == 1
    assert parsed.rows[0] == {
        "instrument_id": "NO0000000005",
        "symbol": "SVEG",
        "name": "SPAREBANKEN VEST",
        "market": "Oslo Børs",
        "currency": "NOK",
        "yfinance_ticker": "SVEG.OL",
    }
    assert [item.reason for item in parsed.rejected_rows] == ["invalid ISIN", "unknown market: Oslo OTC"]


def test_missing_post_header_date_records_nothing(tmp_path: Path) -> None:
    payload = (Path(__file__).parent / "fixtures" / "euronext_oslo_sample.csv").read_bytes()
    stripped = re.sub(rb"01 Oct 2026\r?\n", b"", payload, count=1)
    assert stripped != payload  # the post-header date line was present and removed
    payload = stripped
    config_path = _write_config(tmp_path, minimum_rows=1)

    result = euronext_listing.capture_euronext_oslo_listing(
        root=tmp_path / "store",
        config_path=config_path,
        transport=lambda *_args: (payload, 200),
        clock=lambda: _at("2026-10-01T12:00:00+00:00"),
    )

    assert result.status == "error"
    assert result.reason
    assert capture_log(_SCOPE, root=tmp_path / "store").empty


def test_capture_preserves_raw_response_and_deduplicates_same_snapshot(tmp_path: Path) -> None:
    payload = _csv_payload(
        "01 Oct 2026",
        [
            ("SPAREBANKEN ALFA", _isin(1), "ALFA", "Oslo Børs"),
            ("BANK BETA", _isin(2), "BETA", "Euronext Growth Oslo"),
        ],
    )
    config_path = _write_config(tmp_path, minimum_rows=2)
    times = iter((_at("2026-10-01T12:00:00+00:00"), _at("2026-10-01T13:00:00+00:00")))
    calls: list[tuple[str, bytes, dict[str, str], float]] = []

    def transport(url: str, body: bytes, headers, timeout: float):
        calls.append((url, body, dict(headers), timeout))
        return payload, 200

    first = euronext_listing.capture_euronext_oslo_listing(
        root=tmp_path / "store", config_path=config_path, transport=transport, clock=lambda: next(times)
    )
    second = euronext_listing.capture_euronext_oslo_listing(
        root=tmp_path / "store", config_path=config_path, transport=transport, clock=lambda: next(times)
    )

    assert first.status == "recorded"
    assert second.status == "duplicate"
    assert first.as_of_date == "2026-10-01"
    assert len(capture_log(_SCOPE, root=tmp_path / "store")) == 1
    checksum = hashlib.sha256(payload).hexdigest()
    assert load_raw_payload(checksum, root=tmp_path / "store") == payload
    assert all(item[0] == euronext_listing.ENDPOINT for item in calls)
    assert all(item[1] == euronext_listing.FORM_BODY for item in calls)
    assert all("User-Agent" in item[2] and item[3] > 0 for item in calls)


def test_incomplete_or_unavailable_downloads_record_nothing(tmp_path: Path) -> None:
    one_row = _csv_payload("01 Oct 2026", [("BANK ALFA", _isin(1), "ALFA", "Oslo Børs")])
    cases = (
        ("truncated", lambda: (one_row, 200)),
        ("empty", lambda: (b"", 200)),
        ("missing-header", lambda: (b"European Equities\n01 Oct 2026\nDisclaimer\n", 200)),
        ("http-error", lambda: (b"unavailable", 503)),
        ("network-error", lambda: (_raise_os_error())),
    )
    config_path = _write_config(tmp_path, minimum_rows=2)

    for name, make_response in cases:
        root = tmp_path / name

        def transport(_url: str, _body: bytes, _headers, _timeout: float, *, response=make_response):
            return response()

        result = euronext_listing.capture_euronext_oslo_listing(
            root=root,
            config_path=config_path,
            transport=transport,
            clock=lambda: _at("2026-10-01T12:00:00+00:00"),
        )

        assert result.status == "error", name
        assert result.reason, name
        assert capture_log(_SCOPE, root=root).empty, name


def test_next_snapshot_closes_delisted_instrument(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, minimum_rows=2)
    first_payload = _csv_payload(
        "01 Oct 2026",
        [
            ("SPAREBANKEN ALFA", _isin(1), "ALFA", "Oslo Børs"),
            ("BANK BETA", _isin(2), "BETA", "Oslo Børs"),
        ],
    )
    next_payload = _csv_payload(
        "02 Oct 2026",
        [
            ("BANK BETA", _isin(2), "BETA", "Oslo Børs"),
            ("BANK GAMMA", _isin(3), "GAMMA", "Euronext Expand Oslo"),
        ],
    )

    first = euronext_listing.capture_euronext_oslo_listing(
        root=tmp_path / "store",
        config_path=config_path,
        transport=lambda *_args: (first_payload, 200),
        clock=lambda: _at("2026-10-01T12:00:00+00:00"),
    )
    second = euronext_listing.capture_euronext_oslo_listing(
        root=tmp_path / "store",
        config_path=config_path,
        transport=lambda *_args: (next_payload, 200),
        clock=lambda: _at("2026-10-02T12:00:00+00:00"),
    )

    assert first.status == second.status == "recorded"
    closures = closure_events(_SCOPE, _at("2026-10-02T12:00:00+00:00"), root=tmp_path / "store")
    closed = closures.set_index("instrument_id").loc[_isin(1)]
    assert closed["valid_to"] == "2026-10-02"


def test_savings_bank_view_applies_patterns_includes_and_exclusions(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, minimum_rows=2)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["savings_bank_include_names"].append("DNB BANK")
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rows = [
        ("SPAREBANKEN NORGE", _isin(1), "SPBN", "Oslo Børs"),
        ("VOSS VEKSEL OGLAND", _isin(2), "VOSS", "Oslo Børs"),
        ("HØLAND OG SETSKOG", _isin(3), "HOLAND", "Euronext Growth Oslo"),
        ("DNB BANK", _isin(4), "DNB", "Oslo Børs"),
        ("PARETO BANK", _isin(5), "PARB", "Oslo Børs"),
        ("INSTABANK", _isin(6), "INSTA", "Oslo Børs"),
        ("KRAFT BANK", _isin(7), "KRAFT", "Oslo Børs"),
    ]
    payload = _csv_payload("01 Oct 2026", rows)
    result = euronext_listing.capture_euronext_oslo_listing(
        root=tmp_path / "store",
        config_path=config_path,
        transport=lambda *_args: (payload, 200),
        clock=lambda: _at("2026-10-01T12:00:00+00:00"),
    )

    view = euronext_listing.savings_bank_view(root=tmp_path / "store", config_path=config_path)

    assert result.status == "recorded"
    assert set(view["isin"]) == {_isin(1), _isin(2), _isin(3)}
    assert set(view["symbol"]) == {"SPBN", "VOSS", "HOLAND"}
    assert set(view["yfinance_ticker"]) == {"SPBN.OL", "VOSS.OL", "HOLAND.OL"}
    assert set(view["market"]) == {"Oslo Børs", "Euronext Growth Oslo"}
    assert _isin(4) not in set(view["isin"])


def test_source_policy_registers_non_blocking_optional_listing_provider() -> None:
    policy = next(
        item for item in load_source_policies() if item.provider_id == "euronext_oslo_listing"
    )

    assert policy.dataset_type == "listing"
    assert policy.optional_provider
    assert policy.network_required
    assert policy.quota_failure == "non_blocking"


def _csv_payload(date_text: str, rows: list[tuple[str, str, str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\n")
    writer.writerow(["Name", "ISIN", "Symbol", "Market", "Currency", "Sector"])
    writer.writerow(["European Equities"])
    writer.writerow([date_text])
    writer.writerow(["Public synthetic listing sample."])
    for name, isin, symbol, market in rows:
        writer.writerow([name, isin, symbol, market, "NOK", "Financials"])
    return b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")


def _write_config(tmp_path: Path, *, minimum_rows: int) -> Path:
    payload = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    payload["minimum_rows"] = minimum_rows
    path = tmp_path / "euronext_listing_test.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _isin(serial: int) -> str:
    body = f"NO{serial:09d}"
    for check_digit in "0123456789":
        candidate = f"{body}{check_digit}"
        expanded = "".join(str(ord(character) - 55) if character.isalpha() else character for character in candidate)
        total = 0
        double = False
        for character in reversed(expanded):
            digit = int(character)
            if double:
                digit *= 2
                digit = digit // 10 + digit % 10
            total += digit
            double = not double
        if total % 10 == 0:
            return candidate
    raise AssertionError("could not build synthetic ISIN")


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _raise_os_error():
    raise OSError("synthetic network failure")
