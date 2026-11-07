"""Offline evidence for the live STOXX 600 acquisition layer and the live-shape fixes."""
import io
import json
from pathlib import Path
from urllib.error import HTTPError
import zipfile

import pandas as pd
import pytest

from etf_cockpit.data.esef_provider import FilingsXbrlOrgProvider
from scripts import acquire_stoxx600 as acq
from scripts.ingest_stoxx600 import run_issuers
from tests.test_univ1_stoxx600 import LEI, settings

LEI_A, LEI_B = "529900D6BF99LW9R2E68", "7245003GZ2696Y0W1X57"


def _filing(sequence, added, *, period="2023-12-31", lei=LEI_A):
    return {"type": "filing", "id": f"f{sequence}",
            "attributes": {"period_end": period, "date_added": added, "error_count": 0,
                           "package_url": f"/{lei}/{period}/ESEF/DE/{sequence}/pkg-{sequence}.zip"},
            "relationships": {"entity": {"data": {"type": "entity", "id": "1"}}}}


def _page(rows, *, links, meta=None, lei=LEI_A):
    page = {"data": rows, "links": links,
            "included": [{"type": "entity", "id": "1", "attributes": {"identifier": lei}}]}
    if meta is not None:
        page["meta"] = meta
    return page


def _discover(tmp_path, pages, **kwargs):
    queue = list(pages)
    provider = FilingsXbrlOrgProvider(cache_dir=tmp_path, request_interval=0,
                                      transport=lambda *_: json.dumps(queue.pop(0)).encode())
    return provider.list_issuer_filings(LEI_A, history=True, **kwargs)


def test_live_registry_omits_next_on_last_page_only_with_proven_count(tmp_path):
    rows = [_filing(0, "2024-03-01T12:00:00Z")]
    ok = _discover(tmp_path, [_page(rows, links={"self": "x"}, meta={"count": 1})])
    assert ok.ok and len(ok.data) == 1
    short = _discover(tmp_path, [_page(rows, links={"self": "x"}, meta={"count": 2})])
    assert not short.ok and "next link" in short.message
    unproven = _discover(tmp_path, [_page(rows, links={"self": "x"})])
    assert not unproven.ok


def test_date_only_registry_timestamp_is_known_at_end_of_utc_day(tmp_path):
    result = _discover(tmp_path, [_page([_filing(0, "2024-03-01 00:00:00")], links={"next": None})],
                       date_added_timezone="UTC")
    assert result.data.iloc[0]["known_at"] == "2024-03-01T23:59:59.999999+00:00"
    precise = _discover(tmp_path, [_page([_filing(0, "2024-03-01 13:17:32.5")], links={"next": None})],
                        date_added_timezone="UTC")
    assert precise.data.iloc[0]["known_at"].startswith("2024-03-01T13:17:32.5")


def test_sequence_superseded_at_the_same_instant_is_not_a_separate_version(tmp_path):
    same = _discover(tmp_path, [_page([_filing(0, "2024-03-01T12:00:00Z"), _filing(1, "2024-03-01T12:00:00Z")],
                                      links={"next": None})])
    assert list(same.data["sequence"]) == [1]
    later = _discover(tmp_path, [_page([_filing(0, "2024-03-01T12:00:00Z"), _filing(1, "2024-03-02T12:00:00Z")],
                                       links={"next": None})])
    assert list(later.data["sequence"]) == [0, 1]


def test_per_lei_mapping_known_at_floors_each_issuer(tmp_path):
    base = settings(tmp_path / "base")
    floor = "2030-01-01T00:00:00+00:00"
    plain = run_issuers([LEI], base, workers=1)[0]
    floored = run_issuers([LEI], {**settings(tmp_path / "floor"), "mapping_known_at": {LEI: floor},
                                  "mapping_store": {LEI: "store.json"}}, workers=1)[0]
    assert plain["rows"] and len(floored["rows"]) == len(plain["rows"])
    assert all(row["known_at"] == floor for row in floored["rows"])
    assert all(json.loads(row["source_ref"])["mapping_store"] == "store.json" for row in floored["rows"])
    assert any(row["known_at"] < floor for row in plain["rows"])


def _zip(path, text, name="lei-isin.csv"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, text)


def test_gleif_download_rejects_error_pages_and_retries_transient_http(tmp_path, monkeypatch):
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 408, "Request Time-out", {}, io.BytesIO(b"timeout"))
        return Response(b"<html><body><h1>408 Request Time-out</h1></body></html>" if len(calls) == 2
                        else _zip_bytes("LEI,ISIN\nA,B\n"))

    def _zip_bytes(text):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("x.csv", text)
        return stream.getvalue()

    monkeypatch.setattr(acq, "_OPENER", opener)
    target = tmp_path / "gleif.zip"
    sha, size = acq.download_file("https://mapping.gleif.org/x", target, lambda: None,
                                  acq.validate_gleif_zip, sleep=lambda _: None)
    assert len(calls) == 3 and target.exists() and size == target.stat().st_size and len(sha) == 64
    assert not list(tmp_path.glob("*.part"))
    # Permanent garbage fails closed and publishes nothing.
    calls.clear()
    monkeypatch.setattr(acq, "_OPENER", lambda request, timeout: Response(b"not a zip"))
    other = tmp_path / "other.zip"
    with pytest.raises(ValueError):
        acq.download_file("https://mapping.gleif.org/y", other, lambda: None, acq.validate_gleif_zip,
                          retries=1, sleep=lambda _: None)
    assert not other.exists() and not list(tmp_path.glob("other*"))


def test_filter_vintage_keeps_only_wanted_isins_and_is_resumable(tmp_path):
    source = tmp_path / "v.zip"
    _zip(source, "LEI,ISIN\nL1,AAA\nL2,BBB\nL3,BBB\nL4,CCC\n")
    job = (str(source), ["AAA", "BBB"], str(tmp_path / "filtered.csv"))
    assert acq.filter_vintage(job) == {"AAA": ["L1"], "BBB": ["L2", "L3"]}
    _zip(source, "LEI,ISIN\n")  # changed source: a stale filtered copy must not be reused
    assert acq.filter_vintage(job) == {}


def test_pick_vintages_uses_first_file_on_or_after_target_plus_newest():
    files = [{"id": str(i), "uploadedAt": f"{d}T07:00:00+00:00"} for i, d in
             enumerate(["2020-12-30", "2021-01-02", "2021-06-30", "2021-07-01", "2026-10-22"])]
    chosen = acq.pick_vintages(files, ["2021-01-01", "2021-07-01", "2099-01-01"])
    assert [f["uploadedAt"][:10] for f in chosen] == ["2021-01-02", "2021-07-01", "2026-10-22"]


def test_pair_known_at_requires_same_single_lei_in_every_later_vintage():
    v = lambda **m: {"map": {k: list(x) for k, x in m.items()}}
    vintages = [v(STABLE=["L1"], CHANGED=["L9"], NEW=[]), v(STABLE=["L1"], CHANGED=["L2"]),
                v(STABLE=["L1"], CHANGED=["L2"], NEW=["L3"], GAP=["L5"]), v(STABLE=["L1"], CHANGED=["L2"], NEW=["L3"],
                GAP=["L5"], SHARED_A=["L7"], SHARED_B=["L7"], TWO=["L8", "L9"])]
    pairs, unmapped = acq.derive_pairs(
        ["STABLE", "CHANGED", "NEW", "GAP", "SHARED_A", "SHARED_B", "TWO", "ABSENT"], vintages)
    assert {i: p["first_seen_index"] for i, p in pairs.items()} == {"STABLE": 0, "CHANGED": 1, "NEW": 2, "GAP": 2}
    assert unmapped == {"SHARED_A": "shared_lei_multiple_isins", "SHARED_B": "shared_lei_multiple_isins",
                        "TWO": "conflicting_leis", "ABSENT": "no_gleif_record"}


def test_provider_retries_only_transient_http_failures(tmp_path, monkeypatch):
    from etf_cockpit.data import esef_provider as module
    page = json.dumps(_page([_filing(0, "2024-03-01T12:00:00Z")], links={"next": None})).encode()
    calls = []

    def fake(url, **_):
        calls.append(url)
        if len(calls) == 1:
            raise HTTPError(url, 503, "busy", {}, io.BytesIO(b""))
        if len(calls) == 2:
            raise TimeoutError("slow")
        return page, 200, {}

    sleeps = []
    monkeypatch.setattr(module, "get_checked", fake)
    provider = FilingsXbrlOrgProvider(cache_dir=tmp_path, request_interval=0, retries=2, retry_sleep=sleeps.append)
    assert provider.list_issuer_filings(LEI_A).ok and len(calls) == 3 and sleeps == [1.0, 2.0]
    calls.clear()
    monkeypatch.setattr(module, "get_checked", lambda url, **_: (_ for _ in ()).throw(HTTPError(url, 404, "no", {}, io.BytesIO(b""))))
    permanent = FilingsXbrlOrgProvider(cache_dir=tmp_path, request_interval=0, retries=3, retry_sleep=sleeps.append)
    result = permanent.list_issuer_filings(LEI_A)
    assert not result.ok and "HTTPError" in result.message and sleeps == [1.0, 2.0]
    with pytest.raises(ValueError):
        FilingsXbrlOrgProvider(cache_dir=tmp_path, retries=-1)
