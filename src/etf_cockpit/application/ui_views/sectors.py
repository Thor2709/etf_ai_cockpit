"""Read-only view model for Sectors & Countries (FINAL_UI_SPEC 6.7, 8).

Everything is aggregated from existing results: the dated portfolio exposure cube (ETF look-through, economic
country / sector / entity dimensions) and the stored fund-holdings evidence. Nothing here changes a score, gate,
forecast or portfolio decision. A value that cannot be derived is ``None`` with a reason, never zero. Look-through
buckets carry no return (their constituents have no stored prices); a return only appears where it is the plain
weighted adjusted-close return of the held instruments that make up a classification group.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache

import pandas as pd

from etf_cockpit.app.components.globe import GEOJSON_PATH
from etf_cockpit.application.ui_views.portfolio import herfindahl, hhi_band, window_return

PERSPECTIVES = ("Sector", "Country", "Company")
METRICS = ("P/E", "P/B", "ROE")
WINDOWS = ("1M", "3M", "1Y", "5Y")
SECTOR_GROUPS = ("All", "Tech", "Financials", "Health", "Industrials", "Energy")
REGIONS = ("N. America", "Asia-Pacific", "Europe", "Other")
UNKNOWN = "Unknown/Unmapped"
HISTOGRAM_BINS = ("<−20", "−20", "−10", "0", "10", "20", "30", "40+")
MINUS = "−"
_SHORT = {"Real Estate": "RE", "Consumer Discretionary": "Cons. Disc.", "Communication Services": "Comm.", "Consumer Staples": "Staples", "Information Technology": "Technology", "Health Care": "Health Care"}
_COUNTRY_ALIASES = {"usa": "USA", "us": "USA", "united states": "USA", "uk": "GBR", "united kingdom": "GBR", "korea": "KOR", "south korea": "KOR", "russia": "RUS"}
_FALLBACK_REGION_WORDS = (
    (("america", "usa", "us ", "canada"), "N. America"),
    (("asia", "japan", "china", "pacific", "india", "korea", "taiwan", "australia"), "Asia-Pacific"),
    (("europe", "euro", "germany", "france", "uk", "nordic", "norway"), "Europe"),
)
_BUBBLE_COLUMNS = {
    "P/E": ("pe_ratio", "trailing_pe", "pe"),
    "P/B": ("price_to_book", "pb_ratio", "pb"),
    "ROE": ("return_on_equity", "roe"),
}
_CAP_COLUMNS = ("market_cap", "market_cap_eur", "market_capitalisation")


@dataclass(frozen=True)
class Weight:
    name: str
    weight: float  # percent of the portfolio
    ret: float | None = None  # percent over the selected window
    code: str | None = None  # ISO3 (countries) used by the globe
    short: str | None = None
    parts: tuple[tuple[str, float], ...] = ()  # contributing instruments (name, weight %) for drill-down


@dataclass(frozen=True)
class Bubble:
    name: str
    pe: float | None
    pb: float | None
    roe: float | None
    cap: float | None
    group: str
    ret: float | None = None
    highlight: bool = False


@dataclass
class SectorsView:
    countries: list[Weight] = field(default_factory=list)
    sectors: list[Weight] = field(default_factory=list)
    companies: list[Weight] = field(default_factory=list)
    benchmark_top_country: float | None = None
    region_only: bool = False
    exposure_reason: str | None = None
    sector_reason: str | None = None
    bubbles: list[Bubble] = field(default_factory=list)
    bubbles_reason: str | None = None
    window: str = "1Y"


# ----- geography --------------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _geo() -> dict[str, dict[str, str]]:
    """Lookup tables from the packaged Natural Earth properties (names, ISO codes, continent)."""
    lookup: dict[str, dict[str, str]] = {"by_key": {}, "iso2": {}, "continent": {}, "name": {}}
    data = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    for feature in data["features"]:
        props = feature["properties"]
        iso3 = str(props["ADM0_A3"])
        iso2 = next((str(props[k]) for k in ("ISO_A2", "WB_A2") if str(props.get(k, "-99")) not in {"-99", ""}), iso3[:2])
        name = str(props.get("NAME") or iso3)
        lookup["iso2"][iso3] = iso2
        lookup["continent"][iso3] = str(props.get("CONTINENT", ""))
        lookup["name"][iso3] = name
        for key in (iso3, iso2, name, str(props.get("NAME_LONG", "")), str(props.get("ADMIN", ""))):
            if key and key != "-99":
                lookup["by_key"].setdefault(key.casefold(), iso3)
    return lookup


def iso3_of(label: str) -> str | None:
    key = str(label or "").strip().casefold()
    return _COUNTRY_ALIASES.get(key) if key in _COUNTRY_ALIASES else _geo()["by_key"].get(key)


def country_short(code: str | None, fallback: str) -> str:
    return _geo()["iso2"].get(code or "", fallback[:2].upper())


def region_of(code: str | None) -> str:
    continent = _geo()["continent"].get(code or "", "")
    if continent == "North America":
        return "N. America"
    if continent in {"Asia", "Oceania"}:
        return "Asia-Pacific"
    return "Europe" if continent == "Europe" else "Other"


def region_of_text(label: str) -> str:
    """Coarse region of a free-text classification such as "Europe" or "World" (fallback view only)."""
    text = f" {str(label or '').casefold()} "
    for words, region in _FALLBACK_REGION_WORDS:
        if any(word in text for word in words):
            return region
    return "Other"


def region_shares(countries: Sequence[Weight], *, region_only: bool = False) -> list[tuple[str, float]]:
    """Region bar segments as percent of the exposure that is mapped (labels sum to 100)."""
    totals = dict.fromkeys(REGIONS, 0.0)
    for item in countries:
        region = region_of_text(item.name) if region_only else region_of(item.code)
        totals[region] += item.weight
    whole = sum(totals.values())
    return [(name, totals[name] / whole * 100.0) for name in REGIONS if totals[name] > 0] if whole > 0 else []


# ----- concentration ----------------------------------------------------------------------------------------------


def top_share(items: Sequence[Weight], count: int) -> float | None:
    return sum(item.weight for item in sorted(items, key=lambda i: -i.weight)[:count]) if items else None


def concentration(items: Sequence[Weight]) -> tuple[float | None, str | None]:
    """HHI of the exposure weights (0..1) and its band label (high / moderate / low)."""
    value = herfindahl([item.weight for item in items])
    return value, hhi_band(value)


def headline(items: Sequence[Weight], perspective: str) -> tuple[str | None, str | None]:
    """The strip headline and its sub line (spec 6.7); None when there is no exposure."""
    if not items:
        return None, None
    ordered = sorted(items, key=lambda i: -i.weight)
    noun = {"Sector": "sectors", "Country": "countries", "Company": "companies"}[perspective]
    singular = {"Sector": "sector", "Country": "country", "Company": "company"}[perspective]
    value, _band = concentration(items)
    if ordered[0].weight > 50.0:
        return f"{ordered[0].name} concentration is high", f"{ordered[0].weight:.0f}% of the portfolio sits in one {singular}"
    if value is not None and value >= 0.25:
        return "Exposure is concentrated", f"HHI {value:.2f} across {len(items)} {noun}"
    return "Exposure is diversified", f"Top 5 {noun} hold {top_share(items, 5):.0f}%"


def signed_pct(value: float | None, decimals: int = 0, unit: str = "%") -> str | None:
    if value is None or not math.isfinite(value):
        return None
    sign = "+" if value > 0 else MINUS if value < 0 else ""
    return f"{sign}{abs(value):.{decimals}f}{unit}"


def short_name(name: str) -> str:
    return _SHORT.get(name, name)


# ----- histogram --------------------------------------------------------------------------------------------------


def histogram_counts(returns: Sequence[float | None]) -> tuple[list[int], int, int]:
    """Counts per bin of HISTOGRAM_BINS, the number of negative returns and the number of companies counted."""
    counts = [0] * len(HISTOGRAM_BINS)
    known = [value for value in returns if value is not None and math.isfinite(value)]
    for value in known:
        index = 0 if value < -20 else 7 if value >= 40 else int((value + 20) // 10) + 1
        counts[index] += 1
    return counts, sum(1 for value in known if value < 0), len(known)


def histogram_insight(counts: Sequence[int], negatives: int, total: int) -> str | None:
    if total <= 0:
        return None
    index = max(range(len(counts)), key=lambda i: counts[i])
    start = (-20, -20, -10, 0, 10, 20, 30, 40)[index]
    label = "below −20%" if index == 0 else "above 40%" if index == 7 else f"{start}–{start + 10}%".replace("-", MINUS)
    return f"Most companies return {label}; {negatives} of {total} are negative."


# ----- loading ----------------------------------------------------------------------------------------------------


def _as_of(snapshot: object) -> date | None:
    raw = getattr(getattr(snapshot, "data_report", None), "as_of_date", None)
    try:
        return pd.Timestamp(raw).date()
    except (TypeError, ValueError):
        return None


def current_weights(snapshot: object) -> dict[str, float]:
    holdings = getattr(snapshot, "holdings", None)
    if not isinstance(holdings, pd.DataFrame) or holdings.empty or not {"etf_id", "current_weight"} <= set(holdings.columns):
        return {}
    weights = pd.to_numeric(holdings["current_weight"], errors="coerce")
    result: dict[str, float] = {}
    for key, weight in zip(holdings["etf_id"].astype(str), weights, strict=True):
        if pd.notna(weight) and weight > 0:
            result[key] = result.get(key, 0.0) + float(weight)
    return result


def _cube(weights: Mapping[str, float], snapshot: object, holdings: pd.DataFrame | None) -> tuple[dict[str, object] | None, str | None]:
    from etf_cockpit.application.portfolio_views import load_portfolio_exposure_projection

    as_of = _as_of(snapshot)
    if as_of is None:
        return None, "The snapshot has no as-of date, so exposure cannot be dated."
    decision = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, tzinfo=timezone.utc)
    try:
        return load_portfolio_exposure_projection(weights, decision_time=decision, analysis_date=as_of, holdings=holdings), None
    except (ArithmeticError, KeyError, OSError, TypeError, ValueError) as exc:
        return None, f"Exposure evidence unavailable: {exc}"


def _segments(projection: Mapping[str, object] | None, dimension: str) -> tuple[list[dict[str, object]], float]:
    if not projection:
        return [], 0.0
    rows = [row for row in projection.get("dimensions", {}).get(dimension, []) if row["name"] != UNKNOWN and float(row["percentage"]) > 0]  # type: ignore[union-attr]
    coverage = float(projection.get("coverage", {}).get(dimension, {}).get("coverage_fraction", 0.0))  # type: ignore[union-attr]
    return rows, coverage


def _parts(row: Mapping[str, object]) -> tuple[tuple[str, float], ...]:
    parts: dict[str, float] = {}
    for contributor in row.get("contributors", []):  # type: ignore[union-attr]
        name = str(contributor.get("root_instrument_id"))
        parts[name] = parts.get(name, 0.0) + float(contributor.get("weight", 0.0)) * 100.0
    return tuple(sorted(parts.items(), key=lambda item: -item[1]))


def _look_through(rows: Sequence[Mapping[str, object]], *, countries: bool) -> list[Weight]:
    items = []
    for row in rows:
        name = str(row["name"])
        code = iso3_of(name) if countries else None
        label = _geo()["name"].get(code, name) if code else name
        items.append(Weight(label, float(row["percentage"]), None, code, country_short(code, name) if countries else short_name(name), _parts(row)))
    return sorted(items, key=lambda item: -item.weight)


def _classified(snapshot: object, weights: Mapping[str, float], field_name: str, window: str) -> list[Weight]:
    """Fallback grouping by each holding's configured classification; return = weighted held-instrument return."""
    etfs = {str(etf.id): etf for etf in snapshot.config.universe.etfs}  # type: ignore[attr-defined]
    as_of, prices = _as_of(snapshot), getattr(snapshot, "prices", None)
    groups: dict[str, list[tuple[str, float, float | None]]] = {}
    for key, weight in weights.items():
        etf = etfs.get(key)
        label = str(getattr(etf, field_name, "") or "").strip() if etf is not None else ""
        if not label:
            continue
        ret = window_return(prices, key, window, as_of) if isinstance(prices, pd.DataFrame) else None
        groups.setdefault(label, []).append((key, weight * 100.0, None if ret is None else ret * 100.0))
    result = []
    for label, members in groups.items():
        total = sum(weight for _k, weight, _r in members)
        known = [(weight, ret) for _k, weight, ret in members if ret is not None]
        covered = sum(weight for weight, _r in known)
        ret = sum(weight * r for weight, r in known) / covered if known and covered >= 0.999 * total else None
        result.append(Weight(label, total, ret, None, short_name(label), tuple((k, w) for k, w, _r in members)))
    return sorted(result, key=lambda item: -item.weight)


def _pick(frame: pd.DataFrame, names: Sequence[str]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def bubbles_from_holdings(frame: pd.DataFrame | None, window: str = "1Y") -> tuple[list[Bubble], str | None]:
    """Constituents with stored fundamentals (P/E, P/B, ROE, market cap) from the fund-holdings evidence."""
    reason = "Import benchmark holdings and fundamentals to compare companies."
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return [], reason
    columns = {metric: _pick(frame, names) for metric, names in _BUBBLE_COLUMNS.items()}
    if not any(columns.values()):
        return [], reason
    name_col = _pick(frame, ("security", "holding_name", "company", "name")) or "security"
    sector_col, cap_col = _pick(frame, ("sector",)), _pick(frame, _CAP_COLUMNS)
    ret_col = _pick(frame, (f"return_{window.lower()}", "return_1y", "ret_1y"))
    points: list[Bubble] = []
    for row in frame.to_dict("records"):
        def number(column: str | None) -> float | None:
            value = pd.to_numeric(row.get(column), errors="coerce") if column else None
            return None if value is None or pd.isna(value) else float(value)

        points.append(Bubble(str(row.get(name_col) or "—"), number(columns["P/E"]), number(columns["P/B"]), number(columns["ROE"]), number(cap_col), group_of(str(row.get(sector_col) or "") if sector_col else ""), number(ret_col)))
    return points, None


def group_of(sector: str) -> str:
    text = sector.casefold()
    for group, words in (("Tech", ("tech", "software", "semiconductor", "information")), ("Financials", ("financ", "bank", "insur")), ("Health", ("health", "pharma", "bio")), ("Industrials", ("industr",)), ("Energy", ("energy", "oil"))):
        if any(word in text for word in words):
            return group
    return "Other"


def load(snapshot: object, window: str = "1Y", *, holdings: pd.DataFrame | None = None) -> SectorsView:
    """Build the page data for a snapshot. ``holdings`` is the fund-holdings evidence (loaded locally when None)."""
    from etf_cockpit.application.overlap import load_direct_holdings

    view = SectorsView(window=window)
    weights = current_weights(snapshot)
    if not weights:
        view.exposure_reason = "No current holdings are available in the selected portfolio snapshot."
        view.sector_reason = view.exposure_reason
        view.bubbles_reason = "Import benchmark holdings and fundamentals to compare companies."
        return view
    evidence = holdings if holdings is not None else load_direct_holdings()
    projection, error = _cube(weights, snapshot, evidence)
    country_rows, country_cover = _segments(projection, "economic_country")
    sector_rows, sector_cover = _segments(projection, "sector")
    company_rows, _cover = _segments(projection, "entity")
    if country_rows and country_cover >= 0.01:
        view.countries = _look_through(country_rows, countries=True)
    else:
        view.region_only = True
        view.countries = _classified(snapshot, weights, "region", window)
        view.exposure_reason = error or None
    if sector_rows and sector_cover >= 0.01:
        view.sectors = _look_through(sector_rows, countries=False)
    else:
        view.sectors = _classified(snapshot, weights, "sector", window)
    view.companies = _look_through(company_rows, countries=False)
    if not view.sectors:
        view.sector_reason = error or "No sector classification is available for the held instruments."
    benchmark = str(getattr(snapshot, "benchmark_reference_instrument", "") or "")
    if benchmark and benchmark not in weights and not view.region_only:
        bench_projection, _error = _cube({benchmark: 1.0}, snapshot, evidence)
        rows, cover = _segments(bench_projection, "economic_country")
        if rows and cover >= 0.01:
            view.benchmark_top_country = max(float(row["percentage"]) for row in rows)
    view.bubbles, view.bubbles_reason = bubbles_from_holdings(evidence, window)
    return view
