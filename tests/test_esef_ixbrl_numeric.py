from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from etf_cockpit.parsers import esef_ixbrl


def _parse_fact(tmp_path: Path, monkeypatch, concept: str, text: str, attributes: str):
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: False)
    report = f"""<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:ifrs-full="https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full">
      <body><ix:nonFraction name="ifrs-full:{concept}" {attributes}>
        {text}</ix:nonFraction></body></html>"""
    package = tmp_path / "numeric.xbri"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("META-INF/reportPackage.json", "{}")
        archive.writestr("reports/report.xhtml", report)
    result = esef_ixbrl.parse_esef_package(package)
    assert result.success is True
    assert not any(warning.code == "unsupported_numeric_fact" for warning in result.warnings)
    assert len(result.records) == 1
    return result.records[0]


@pytest.mark.parametrize("separator", [" ", "\u00a0", "\u202f", "\u2009"], ids=["space", "nbsp", "nnbsp", "thin-space"])
@pytest.mark.parametrize("format_name,decimal", [("num-dot-decimal", "."), ("num-comma-decimal", ",")])
def test_decimal_formats_decode_group_separators(separator: str, format_name: str, decimal: str) -> None:
    text = f"1{separator}234{separator}567{decimal}89"
    assert esef_ixbrl._decode_numeric_fact(text, {"format": f"ixt:{format_name}"}) == ("1234567.89", None)
    # Space grouping remains unsupported without an explicit decimal transform.
    assert esef_ixbrl._decode_numeric_fact(text, {}) == (text, "value is not a plain decimal number")
    assert esef_ixbrl._decode_numeric_fact(text, {"format": "ixt:numwordsen"}) == (
        text, "unsupported format ixt:numwordsen"
    )
    assert esef_ixbrl._decode_numeric_fact("-", {"format": "ixt:zerodash"}) == ("0", None)


@pytest.mark.parametrize("separator", [" ", "\u00a0", "\u202f", "\u2009"], ids=["space", "nbsp", "nnbsp", "thin-space"])
@pytest.mark.parametrize("format_name", ["num-dot-decimal", "num-comma-decimal"])
@pytest.mark.parametrize("scale,expected", [(3, "212757000"), (6, "212757000000")])
def test_grouped_share_count_is_scaled_after_decode(
    tmp_path: Path, monkeypatch, separator: str, format_name: str, scale: int, expected: str
) -> None:
    fact = _parse_fact(
        tmp_path, monkeypatch, "NumberOfSharesOutstanding", f"212{separator}757",
        f'format="ixt:{format_name}" scale="{scale}"',
    )
    assert fact.value == expected
    assert fact.mapping_status == "mapped"
    assert esef_ixbrl.map_ifrs_fact(fact.concept, fact.namespace) == "shares_outstanding"


@pytest.mark.parametrize("concept", ["WeightedAverageShares", "WeightedAverageNumberOfOrdinarySharesOutstandingBasic"])
def test_weighted_average_shares_never_map_to_outstanding_shares(tmp_path: Path, monkeypatch, concept: str) -> None:
    fact = _parse_fact(tmp_path, monkeypatch, concept, "212757", "")
    assert fact.mapping_status == "mapped"
    metric = esef_ixbrl.map_ifrs_fact(f"ifrs-full:{fact.concept}", fact.namespace)
    assert metric == "weighted_average_shares"
    assert metric != "shares_outstanding"
