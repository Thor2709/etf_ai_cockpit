"""Point-in-time news/context contracts and local-first persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR
from etf_cockpit.data.event_calendar import _frame_checksum
from etf_cockpit.core.values import aware_utc_timestamp_or_none as _contradiction_timestamp


NEWS_SCHEMA_VERSION = "news_context.v2"
NEWS_CLEAN_PATH = CLEAN_DIR / "news_context.parquet"
NEWS_RAW_DIR = RAW_DIR / "news_context"


@dataclass(frozen=True)
class NewsItem:
    # The first nine fields preserve the original positional API.
    news_id: str = ""
    instrument_id: str = ""
    source: str = ""
    provider: str = ""
    headline: str = ""
    published_at: str = ""
    ingested_at: str = ""
    url: str = ""
    credibility: str = "unverified"
    instrument_mapping_method: str = ""
    available_at_decision_time: bool | None = None
    timezone_name: str = "UTC"
    timestamp_confidence: str = "exact"
    current_only: bool = False
    revised: bool = False
    context_only: bool = True
    executable_authority: bool = False
    source_url: str | None = None
    provider_name: str | None = None
    timezone: str | None = None

    def __post_init__(self) -> None:
        if self.source_url is None:
            object.__setattr__(self, "source_url", self.url)
        if self.provider_name is None:
            object.__setattr__(self, "provider_name", self.provider)
        if self.timezone:
            object.__setattr__(self, "timezone_name", self.timezone)

    @property
    def source_url_value(self) -> str:
        return str(self.source_url or self.url or "").strip()

    @property
    def provider_name_value(self) -> str:
        return str(self.provider_name or self.provider or "").strip()


@dataclass(frozen=True)
class NewsValidation:
    status: str
    backtest_eligible: bool
    reason: str
    context_only: bool = True
    executable_authority: bool = False
    available_at_decision_time: bool = False
    timestamp_confidence: str = "unknown"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewsPersistenceResult:
    raw_paths: tuple[Path, ...]
    clean_path: Path
    audit_path: Path
    rows: int
    checksum: str
    idempotent: bool = False


def validate_news_item(item: NewsItem, decision_time: datetime) -> NewsValidation:
    """Validate metadata required to use an item in a point-in-time backtest."""

    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        return _invalid("ambiguous_timestamp", "Decision timestamp must include an explicit timezone.")
    published, _ = _parse_timestamp(item.published_at)
    ingested, _ = _parse_timestamp(item.ingested_at)
    if published is None or ingested is None:
        return _invalid("ambiguous_timestamp", "Published/ingested timestamp must be ISO-8601 with timezone.")
    if str(item.timestamp_confidence or "").strip().lower() in {"ambiguous", "local", "unknown"} or str(item.timezone_name or "").strip().lower() in {"local", "unknown", "ambiguous"}:
        return _invalid("ambiguous_timestamp", "News timestamp timezone/confidence is ambiguous.")
    if item.current_only or item.revised:
        return _invalid("current_only_revised", "Current-only or revised news cannot be used for point-in-time backtests.")
    if published > decision_time or ingested > decision_time:
        return _invalid("after_decision_time", "News was not available at the decision time.")
    if not item.source_url_value or not item.provider_name_value or not str(item.instrument_id).strip() or not str(item.instrument_mapping_method).strip():
        return _invalid("missing_provenance", "News source URL, provider, instrument mapping and timestamps are required.")
    if item.available_at_decision_time is not True:
        return _invalid("not_available_at_decision", "Provider did not prove that the item was available at the decision time.")
    return NewsValidation(
        "valid_context",
        True,
        "Timestamp and provenance are valid; news remains context-only.",
        context_only=True,
        executable_authority=False,
        available_at_decision_time=True,
        timestamp_confidence="exact",
    )


def persist_news_items(
    items: Iterable[NewsItem],
    *,
    raw_dir: Path = NEWS_RAW_DIR,
    clean_path: Path = NEWS_CLEAN_PATH,
    audit_path: Path | None = None,
    decision_time: datetime | None = None,
) -> NewsPersistenceResult:
    """Persist immutable raw news and an idempotent canonical clean ledger."""

    raw_dir = Path(raw_dir)
    clean_path = Path(clean_path)
    audit_path = Path(audit_path or clean_path.with_name(clean_path.stem + "_audit.json"))
    item_tuple = tuple(items)
    if not item_tuple:
        raise ValueError("At least one news item is required.")
    # Read the current canonical generation before creating raw outputs.  A
    # corrupt or malformed ledger must fail closed rather than being treated as
    # empty and replaced by a clean-looking generation.
    existing = _read_clean_strict(clean_path)
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_paths: list[Path] = []
    raw_requests: list[AtomicWriteRequest] = []
    rows: list[dict[str, Any]] = []
    validations: list[dict[str, Any]] = []
    for item in item_tuple:
        payload = _item_payload(item)
        checksum = _payload_checksum(payload)
        raw_path = raw_dir / f"{_safe_id(item.news_id)}-{checksum}.json"
        if not raw_path.exists():
            raw_requests.append(
                AtomicWriteRequest(
                    raw_path,
                    (json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8"),
                    lambda path: json.loads(path.read_text(encoding="utf-8")),
                )
            )
        raw_paths.append(raw_path)
        validation = validate_news_item(item, decision_time or _default_decision_time(item))
        rows.append(_clean_row(item, validation, checksum, raw_path))
        validations.append({"news_id": item.news_id, **asdict(validation), "executable_authority": False})

    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    if not combined.empty:
        combined = combined.drop_duplicates(subset=["news_id", "item_checksum"], keep="last")
        combined = sort_news_items(combined)
    audit_payload = {
        "schema_version": NEWS_SCHEMA_VERSION,
        "dataset_type": "news_context",
        "raw_paths": [str(path) for path in raw_paths],
        "clean_path": str(clean_path),
        "checksum": _frame_checksum(combined),
        "rows": len(combined),
        "validations": validations,
        "context_only": True,
        "executable_authority": False,
    }
    csv_path = clean_path.with_suffix(".csv")
    requests = [
        AtomicWriteRequest(clean_path, parquet_payload(combined), validate_parquet_file),
        AtomicWriteRequest(csv_path, combined.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
        AtomicWriteRequest(audit_path, (json.dumps(audit_payload, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8"), lambda path: json.loads(path.read_text(encoding="utf-8"))),
        *raw_requests,
    ]
    # Raw provider payloads are immutable and part of the same generation as
    # clean/audit mirrors. Existing raw bytes are intentionally not rewritten.
    atomic_write_group(tuple(requests))
    checksum = _payload_checksum(_item_payload(item_tuple[0]))
    return NewsPersistenceResult(tuple(raw_paths), clean_path, audit_path, len(combined), checksum, len(existing) == len(combined))


def load_news_items(path: Path = NEWS_CLEAN_PATH, *, strict: bool = False) -> pd.DataFrame:
    """Read the canonical news ledger, preserving unreadable versus empty state."""

    frame = _read_clean_strict(Path(path)) if strict else _read_clean(Path(path))
    return sort_news_items(frame)


def sort_news_items(frame: pd.DataFrame) -> pd.DataFrame:
    """Return news ordered by publication/ingestion time and stable identity."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    result = frame.copy()
    result["_published_sort"] = pd.to_datetime(result.get("published_at", pd.Series(index=result.index)), errors="coerce", utc=True)
    result["_ingested_sort"] = pd.to_datetime(result.get("ingested_at", pd.Series(index=result.index)), errors="coerce", utc=True)
    result["_news_id_sort"] = result.get("news_id", pd.Series(index=result.index)).astype(str)
    result["_checksum_sort"] = result.get("item_checksum", pd.Series(index=result.index)).astype(str)
    result = result.sort_values(
        ["_published_sort", "_ingested_sort", "_news_id_sort", "_checksum_sort"],
        kind="stable",
        na_position="first",
    )
    return result.drop(columns=["_published_sort", "_ingested_sort", "_news_id_sort", "_checksum_sort"]).reset_index(drop=True)


def build_news_contradiction_rows(news: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Compare explicit headline direction with the next deterministic close.

    Only unambiguous direction words and dated price rows are compared.  No
    sentiment is inferred from free text; unsupported rows remain absent from
    the contradiction set and are shown as unavailable by the UI.
    """

    columns = ["news_id", "instrument_id", "headline", "headline_direction", "price_direction", "reason"]
    if news.empty or prices.empty:
        return pd.DataFrame(columns=columns)
    required = {"instrument_id", "published_at", "headline"}
    if not required <= set(news.columns) or not {"instrument_id", "date", "adjusted_close"} <= set(prices.columns):
        return pd.DataFrame(columns=columns)
    price_frame = prices.copy()
    instrument = price_frame["instrument_id"].map(lambda value: str(value).strip())
    etf = price_frame["etf_id"].map(lambda value: str(value).strip()) if "etf_id" in price_frame.columns else pd.Series("", index=price_frame.index)
    if bool((instrument.ne("") & etf.ne("") & instrument.ne(etf)).any()):
        return pd.DataFrame(columns=columns)
    price_frame["instrument_id"] = instrument.where(instrument.ne(""), etf)
    price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce").dt.date
    price_frame["adjusted_close"] = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    price_frame = price_frame.dropna(subset=["date", "adjusted_close"])
    rows: list[dict[str, object]] = []
    positive = ("up", "rise", "rises", "gain", "gains", "higher", "surge", "surges", "rally", "rallies")
    negative = ("down", "fall", "falls", "loss", "losses", "lower", "drop", "drops", "selloff")
    for _, item in news.iterrows():
        headline = str(item.get("headline", ""))
        lowered = headline.casefold()
        has_positive = re.search(r"(?<!\w)(?:" + "|".join(map(re.escape, positive)) + r")(?!\w)", lowered) is not None
        has_negative = re.search(r"(?<!\w)(?:" + "|".join(map(re.escape, negative)) + r")(?!\w)", lowered) is not None
        headline_direction = (
            "up"
            if has_positive and not has_negative
            else "down"
            if has_negative and not has_positive
            else "unknown"
        )
        if headline_direction == "unknown":
            continue
        published = pd.to_datetime(item.get("published_at"), errors="coerce")
        if pd.isna(published):
            continue
        instrument = str(item.get("instrument_id", "")).strip()
        scoped = price_frame[price_frame["instrument_id"].astype(str).eq(instrument)].sort_values("date")
        prior = scoped[scoped["date"] <= published.date()]
        following = scoped[scoped["date"] > published.date()]
        if prior.empty or following.empty:
            continue
        change = float(following.iloc[0]["adjusted_close"]) - float(prior.iloc[-1]["adjusted_close"])
        price_direction = "up" if change > 0 else "down" if change < 0 else "flat"
        if price_direction in {"flat", headline_direction}:
            continue
        rows.append({
            "news_id": str(item.get("news_id", "")),
            "instrument_id": instrument,
            "headline": headline,
            "headline_direction": headline_direction,
            "price_direction": price_direction,
            "reason": "Explicit headline direction disagrees with the next dated deterministic close.",
        })
    return pd.DataFrame(rows, columns=columns)


CONTRADICTION_RULES = (
    "positive_trend_negative_news",
    "positive_news_weak_fundamentals",
    "macro_risk_against_exposure",
    "source_disagreement",
    "bullish_sentiment_deteriorating_score",
    "strong_score_missing_stale_news",
)


@dataclass(frozen=True)
class ContradictionResult:
    """One informational, point-in-time contradiction classification."""

    rule: str
    status: str
    reason: str
    instrument_id: str | None = None
    evidence: Mapping[str, object] = ()
    execution_allowed: bool = False
    executable_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "status": self.status,
            "reason": self.reason,
            "instrument_id": self.instrument_id,
            "evidence": dict(self.evidence) if isinstance(self.evidence, Mapping) else {},
            "execution_allowed": False,
            "executable_authority": False,
        }


def build_news_macro_contradictions(
    news: pd.DataFrame,
    *,
    prices: pd.DataFrame | None = None,
    fundamentals: pd.DataFrame | None = None,
    macro_context: Mapping[str, object] | None = None,
    exposures: object | None = None,
    score_history: pd.DataFrame | None = None,
    cutoff: object | None = None,
    freshness_days: int = 7,
    source_window_days: int = 3,
    strong_score_threshold: float = 7.0,
) -> list[dict[str, object]]:
    """Classify news/macro contradictions using only evidence known by cutoff.

    Every rule is represented even when its inputs are unavailable.  This
    function is deliberately context-only: it never mutates or supplies score
    or action values.
    """

    cutoff_ts = _contradiction_timestamp(cutoff)
    if cutoff_ts is None:
        return [_unavailable_result(rule, "An explicit decision cutoff is required for point-in-time contradiction evaluation.").to_dict() for rule in CONTRADICTION_RULES]
    eligible_news = _eligible_contradiction_news(news, cutoff_ts)
    eligible_prices = _eligible_contradiction_prices(prices, cutoff_ts)
    results: list[ContradictionResult] = []
    results.extend(_positive_trend_rule(eligible_news, eligible_prices, cutoff_ts))
    results.extend(_weak_fundamentals_rule(eligible_news, fundamentals, cutoff_ts))
    results.extend(_macro_exposure_rule(macro_context, exposures))
    results.extend(_source_disagreement_rule(eligible_news, source_window_days))
    results.extend(_deteriorating_score_rule(eligible_news, score_history, cutoff_ts))
    results.extend(_missing_stale_news_rule(eligible_news, score_history, cutoff_ts, freshness_days, strong_score_threshold))
    return [result.to_dict() for result in results]


# Descriptive aliases keep callers independent of the historical function name.
evaluate_news_macro_contradictions = build_news_macro_contradictions
build_contradiction_results = build_news_macro_contradictions


def _positive_trend_rule(news: pd.DataFrame, prices: pd.DataFrame | None, cutoff: pd.Timestamp | None) -> list[ContradictionResult]:
    rule = "positive_trend_negative_news"
    if news.empty:
        return [_unavailable_result(rule, "No point-in-time news items are available at the evaluation cutoff.")]
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        return [_unavailable_result(rule, "Adjusted-price evidence is unavailable at the evaluation cutoff.")]
    if "_identity_error" in prices.columns:
        return [_unavailable_result(rule, str(prices["_identity_error"].iloc[0]))]
    rows = build_news_contradiction_rows(news, prices)
    if rows.empty:
        return [_clear_result(rule, "No positive trend headline contradicts the next available adjusted close.")]
    return [
        ContradictionResult(
            rule,
            "flagged",
            str(row.get("reason", "Headline direction contradicts the next adjusted close.")),
            str(row.get("instrument_id") or "") or None,
            {key: row.get(key) for key in ("news_id", "headline_direction", "price_direction")},
        )
        for _, row in rows.iterrows()
    ]


def _weak_fundamentals_rule(news: pd.DataFrame, fundamentals: pd.DataFrame | None, cutoff: pd.Timestamp | None) -> list[ContradictionResult]:
    rule = "positive_news_weak_fundamentals"
    positive = news.loc[news["headline"].map(_headline_direction).eq("up")] if not news.empty else pd.DataFrame()
    if positive.empty:
        return [_clear_result(rule, "No positive point-in-time news headline is present.")]
    if not isinstance(fundamentals, pd.DataFrame) or fundamentals.empty:
        return [_unavailable_result(rule, "Canonical fundamentals quality outputs are unavailable for the positive-news instrument(s).")]
    rows: list[ContradictionResult] = []
    for instrument_id, items in positive.groupby(positive["instrument_id"].astype(str), sort=True):
        row = _latest_evidence_row(fundamentals, instrument_id, cutoff)
        if row is None:
            rows.append(_unavailable_result(rule, f"Canonical fundamentals quality output is unavailable for {instrument_id}.", instrument_id))
            continue
        quality = _quality_value(row)
        if quality is None:
            rows.append(_unavailable_result(rule, f"Canonical fundamentals quality output is missing for {instrument_id}.", instrument_id))
            continue
        weak = quality <= (0.4 if abs(quality) <= 1.0 else 5.0)
        rows.append(
            ContradictionResult(
                rule,
                "flagged" if weak else "clear",
                "Positive news conflicts with weak canonical fundamentals quality." if weak else "Positive news is not contradicted by the available fundamentals quality output.",
                instrument_id,
                {"quality_score": quality, "news_ids": tuple(items["news_id"].astype(str))},
            )
        )
    return rows


def _macro_exposure_rule(macro_context: Mapping[str, object] | None, exposures: object | None) -> list[ContradictionResult]:
    rule = "macro_risk_against_exposure"
    if not isinstance(macro_context, Mapping) or str(macro_context.get("status", "unavailable")).casefold() not in {"available", "available_with_gaps"}:
        reason = "Macro context unavailable; macro contradiction comparison is unavailable."
        return [_unavailable_result(rule, reason)]
    exposure_rows = _exposure_rows(exposures)
    if not exposure_rows:
        return [_unavailable_result(rule, "macro contradiction comparison is unavailable: instrument exposure/classification is unavailable for macro comparison.")]
    regime = macro_context.get("regime") if isinstance(macro_context.get("regime"), Mapping) else {}
    label = str(regime.get("label") or regime.get("dashboard_label") or "").casefold()
    score = _finite_number(regime.get("score_10"))
    if not label and score is None:
        return [_unavailable_result(rule, "Macro context regime is unavailable at the evaluation cutoff.")]
    stressed = label in {"stressed", "defensive", "risk-off", "risk_off"} or (score is not None and score <= 4.0)
    rows: list[ContradictionResult] = []
    for instrument_id, classification in exposure_rows:
        if not classification.strip():
            rows.append(_unavailable_result(rule, "Exposure classification is missing; macro sensitivity cannot be established.", instrument_id))
            continue
        equity = any(term in classification.casefold() for term in ("equity", "stock", "risk", "high_beta"))
        if not equity:
            rows.append(_clear_result(rule, "Exposure classification is not sensitive to the identified macro regime.", instrument_id, {"regime": label or "unavailable"}))
        else:
            rows.append(ContradictionResult(rule, "flagged" if stressed else "clear", "Macro regime is adverse to the instrument exposure classification." if stressed else "Macro regime is not adverse to the instrument exposure classification.", instrument_id, {"regime": label or "unavailable", "regime_score_10": score}))
    return rows


def _source_disagreement_rule(news: pd.DataFrame, window_days: int) -> list[ContradictionResult]:
    rule = "source_disagreement"
    if news.empty:
        return [_unavailable_result(rule, "No point-in-time news items are available at the evaluation cutoff.")]
    flagged: list[ContradictionResult] = []
    comparable_pairs = 0
    for instrument_id, group in news.groupby(news["instrument_id"].astype(str), sort=True):
        records = [(row, _headline_direction(row.get("headline"))) for _, row in group.iterrows()]
        for left_index, (left, left_direction) in enumerate(records):
            if left_direction not in {"up", "down"}:
                continue
            left_source = str(left.get("provider_name") or left.get("provider") or left.get("source_authority") or left.get("source") or "").strip()
            left_time = _contradiction_timestamp(left.get("published_at"))
            for right, right_direction in records[left_index + 1 :]:
                right_source = str(right.get("provider_name") or right.get("provider") or right.get("source_authority") or right.get("source") or "").strip()
                right_time = _contradiction_timestamp(right.get("published_at"))
                if right_direction not in {"up", "down"} or not left_source or left_source == right_source or left_time is None or right_time is None:
                    continue
                if abs((left_time - right_time).total_seconds()) <= max(0, window_days) * 86400:
                    comparable_pairs += 1
                    if left_direction != right_direction:
                        flagged.append(ContradictionResult(rule, "flagged", "Different sources/providers report opposite headline directions within the bounded window.", instrument_id, {"news_ids": (str(left.get("news_id", "")), str(right.get("news_id", ""))), "sources": (left_source, right_source)}))
                        break
            if flagged and flagged[-1].instrument_id == instrument_id:
                break
    if flagged:
        return flagged
    if comparable_pairs == 0:
        return [_unavailable_result(rule, "No comparable multi-source/provider evidence exists in the bounded window.")]
    return [_clear_result(rule, "No opposite headline directions from different sources were found in the bounded window.")]


def _deteriorating_score_rule(news: pd.DataFrame, history: pd.DataFrame | None, cutoff: pd.Timestamp | None) -> list[ContradictionResult]:
    rule = "bullish_sentiment_deteriorating_score"
    positive = news.loc[news["headline"].map(_headline_direction).eq("up")] if not news.empty else pd.DataFrame()
    if positive.empty:
        return [_clear_result(rule, "No bullish point-in-time sentiment headline is present.")]
    pairs = _score_pairs(history, cutoff)
    if pairs is None:
        return [_unavailable_result(rule, "Two attributable score-history runs at or before the evaluation cutoff are unavailable.")]
    rows: list[ContradictionResult] = []
    for instrument_id in sorted(set(positive["instrument_id"].astype(str))):
        previous, current = _score_values(pairs, instrument_id)
        if previous is None or current is None:
            rows.append(_unavailable_result(rule, f"Score history for {instrument_id} is missing or non-numeric at the evaluation cutoff.", instrument_id))
            continue
        rows.append(ContradictionResult(rule, "flagged" if current < previous else "clear", "Bullish sentiment conflicts with a deteriorating final combined score." if current < previous else "Bullish sentiment is not contradicted by the latest attributable score runs.", instrument_id, {"previous_score": previous, "current_score": current}))
    return rows


def _missing_stale_news_rule(news: pd.DataFrame, history: pd.DataFrame | None, cutoff: pd.Timestamp | None, freshness_days: int, threshold: float) -> list[ContradictionResult]:
    rule = "strong_score_missing_stale_news"
    if cutoff is None:
        return [_unavailable_result(rule, "An explicit evaluation cutoff is required to classify news freshness.")]
    pairs = _score_pairs(history, cutoff)
    if pairs is None:
        return [_unavailable_result(rule, "An attributable score run at or before the evaluation cutoff is unavailable.")]
    current = pairs[1]
    if current.empty or "instrument_id" not in current.columns or "final_combined_score_10" not in current.columns:
        return [_unavailable_result(rule, "Strong-score rows are unavailable at the evaluation cutoff.")]
    rows: list[ContradictionResult] = []
    for _, score_row in current.iterrows():
        instrument_id = str(score_row.get("instrument_id") or score_row.get("etf_id") or "").strip()
        score = _finite_number(score_row.get("final_combined_score_10"))
        if not instrument_id or score is None or score < threshold:
            continue
        scoped = news.loc[news["instrument_id"].astype(str).eq(instrument_id)] if not news.empty else pd.DataFrame()
        fresh = False
        if cutoff is not None and not scoped.empty:
            published = scoped["published_at"].map(_contradiction_timestamp)
            fresh = bool(published.map(lambda value: value is not None and (cutoff - value).total_seconds() <= max(0, freshness_days) * 86400).any())
        rows.append(ContradictionResult(rule, "clear" if fresh else "flagged", "A fresh news item is available within the configured window." if fresh else "Strong score has no news item within the freshness window at the evaluation cutoff; missing/stale news is not clear.", instrument_id, {"final_combined_score_10": score, "freshness_days": freshness_days}))
    return rows or [_unavailable_result(rule, "No strong score tier rows are present at the evaluation cutoff.")]


def _eligible_contradiction_news(news: pd.DataFrame, cutoff: pd.Timestamp | None) -> pd.DataFrame:
    if not isinstance(news, pd.DataFrame) or news.empty or not {"instrument_id", "headline", "published_at"} <= set(news.columns):
        return pd.DataFrame(columns=list(news.columns) if isinstance(news, pd.DataFrame) else [])
    frame = news.copy()
    frame["instrument_id"] = frame["instrument_id"].astype(str).str.strip()
    published = frame["published_at"].map(_contradiction_timestamp)
    ingested = frame["ingested_at"].map(_contradiction_timestamp) if "ingested_at" in frame.columns else pd.Series(pd.NaT, index=frame.index)
    mask = frame["instrument_id"].ne("") & published.notna() & ingested.notna()
    if cutoff is not None:
        published_before = published.map(lambda value: isinstance(value, pd.Timestamp) and not pd.isna(value) and value <= cutoff)
        ingested_before = ingested.map(lambda value: isinstance(value, pd.Timestamp) and not pd.isna(value) and value <= cutoff)
        mask &= published_before & ingested_before
    frame = frame.loc[mask].copy()
    frame["_published_ts"] = published.loc[frame.index]
    return frame.sort_values(["_published_ts", "instrument_id"], kind="stable").drop(columns=["_published_ts"]).reset_index(drop=True)


def _eligible_contradiction_prices(prices: pd.DataFrame | None, cutoff: pd.Timestamp | None) -> pd.DataFrame:
    if not isinstance(prices, pd.DataFrame) or prices.empty or cutoff is None or "date" not in prices.columns:
        return prices if isinstance(prices, pd.DataFrame) else pd.DataFrame()
    frame = prices.copy()
    instrument = frame["instrument_id"].map(lambda value: str(value).strip()) if "instrument_id" in frame.columns else pd.Series("", index=frame.index)
    etf = frame["etf_id"].map(lambda value: str(value).strip()) if "etf_id" in frame.columns else pd.Series("", index=frame.index)
    conflicts = instrument.ne("") & etf.ne("") & instrument.ne(etf)
    if bool(conflicts.any()):
        frame["_identity_error"] = "Conflicting instrument_id and etf_id identities; price evidence is unavailable."
        return frame
    frame["instrument_id"] = instrument.where(instrument.ne(""), etf)
    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    return frame.loc[dates.notna() & dates.dt.date.le(cutoff.date())].copy()


def _latest_evidence_row(frame: pd.DataFrame, instrument_id: str, cutoff: pd.Timestamp | None) -> dict[str, object] | None:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "instrument_id" not in frame.columns:
        return None
    scoped = frame.loc[frame["instrument_id"].astype(str).eq(instrument_id)].copy()
    date_column = next((column for column in ("as_of_date", "as_of", "available_at", "published_at") if column in scoped.columns), None)
    if date_column is None:
        return None
    timestamps = scoped[date_column].map(_evidence_timestamp)
    scoped = scoped.loc[timestamps.notna()]
    if cutoff is not None:
        scoped = scoped.loc[timestamps.loc[scoped.index].le(cutoff)]
    availability_column = next((column for column in ("available_at", "availability_date", "published_at", "publication_date", "filing_date", "fundamental_available_at") if column in scoped.columns), None)
    if availability_column is not None:
        available = scoped[availability_column].map(_evidence_timestamp)
        scoped = scoped.loc[available.notna()]
        if cutoff is not None:
            scoped = scoped.loc[available.loc[scoped.index].le(cutoff)]
    if scoped.empty:
        return None
    scoped = scoped.assign(_evidence_ts=timestamps.loc[scoped.index]).sort_values("_evidence_ts", kind="stable")
    return scoped.drop(columns=["_evidence_ts"]).iloc[-1].to_dict()


def _quality_value(row: Mapping[str, object]) -> float | None:
    for key in ("quality_score", "fundamental_quality_10", "quality_10", "quality"):
        value = _finite_number(row.get(key))
        if value is not None:
            return value
    return None


def _score_pairs(history: pd.DataFrame | None, cutoff: pd.Timestamp | None) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    if not isinstance(history, pd.DataFrame) or history.empty or "run_id" not in history.columns or "run_completed_at" not in history.columns:
        return None
    frame = history.copy()
    completed = frame["run_completed_at"].map(_contradiction_timestamp)
    frame = frame.loc[completed.notna()]
    if cutoff is not None:
        frame = frame.loc[completed.loc[frame.index].le(cutoff)]
    runs = frame[["run_id", "run_completed_at"]].drop_duplicates("run_id")
    runs["_ts"] = runs["run_completed_at"].map(_contradiction_timestamp)
    runs = runs.sort_values(["_ts", "run_id"], kind="stable")
    if runs.empty:
        return None
    current_id = str(runs.iloc[-1]["run_id"])
    previous_id = str(runs.iloc[-2]["run_id"]) if len(runs) >= 2 else current_id
    current = frame.loc[frame["run_id"].astype(str).eq(current_id)].copy()
    previous = frame.loc[frame["run_id"].astype(str).eq(previous_id)].copy()
    return (previous, current) if len(runs) >= 2 else (pd.DataFrame(), current)


def _score_values(pairs: tuple[pd.DataFrame, pd.DataFrame] | None, instrument_id: str) -> tuple[float | None, float | None]:
    if pairs is None:
        return None, None
    previous, current = pairs
    def read(frame: pd.DataFrame) -> float | None:
        if frame.empty or "instrument_id" not in frame.columns or "final_combined_score_10" not in frame.columns:
            return None
        scoped = frame.loc[frame["instrument_id"].astype(str).eq(instrument_id)]
        return _finite_number(scoped.iloc[-1]["final_combined_score_10"]) if not scoped.empty else None
    return read(previous), read(current)


def _exposure_rows(exposures: object) -> list[tuple[str, str]]:
    if isinstance(exposures, pd.DataFrame):
        rows = exposures.to_dict(orient="records")
    elif isinstance(exposures, Mapping):
        rows = [{"instrument_id": key, "classification": value} for key, value in exposures.items()]
    elif isinstance(exposures, Iterable) and not isinstance(exposures, (str, bytes)):
        rows = list(exposures)
    else:
        rows = []
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        instrument_id = str(row.get("instrument_id") or row.get("etf_id") or row.get("id") or "").strip()
        classification = " ".join(str(row.get(key) or "") for key in ("classification", "asset_class", "asset_type", "sector", "role", "theme"))
        if instrument_id:
            result.append((instrument_id, classification))
    return result


def _headline_direction(headline: object) -> str:
    text = str(headline or "").casefold()
    positive = ("up", "rise", "rises", "gain", "gains", "higher", "surge", "surges", "rally", "rallies", "bullish", "beat", "positive")
    negative = ("down", "falls", "fall", "loss", "losses", "lower", "drop", "drops", "selloff", "bearish", "negative", "weak")
    has_positive = re.search(r"(?<!\w)(?:" + "|".join(map(re.escape, positive)) + r")(?!\w)", text) is not None
    has_negative = re.search(r"(?<!\w)(?:" + "|".join(map(re.escape, negative)) + r")(?!\w)", text) is not None
    return "up" if has_positive and not has_negative else "down" if has_negative and not has_positive else "unknown"


def _evidence_timestamp(value: object) -> pd.Timestamp | None:
    timestamp = _contradiction_timestamp(value)
    if timestamp is not None:
        return timestamp
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None and parsed.utcoffset() is None and parsed.time() == datetime.min.time():
        return parsed.tz_localize("UTC")
    return None


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) and math.isfinite(number) else None


def _unavailable_result(rule: str, reason: str, instrument_id: str | None = None) -> ContradictionResult:
    return ContradictionResult(rule, "unavailable", reason, instrument_id)


def _clear_result(rule: str, reason: str, instrument_id: str | None = None, evidence: Mapping[str, object] | None = None) -> ContradictionResult:
    return ContradictionResult(rule, "clear", reason, instrument_id, evidence or {})


def _invalid(status: str, reason: str) -> NewsValidation:
    return NewsValidation(status, False, reason, context_only=True, executable_authority=False, available_at_decision_time=False, timestamp_confidence="invalid")


def _parse_timestamp(value: object) -> tuple[datetime | None, str]:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None, "invalid"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "ambiguous"
    return parsed, "exact"


def _default_decision_time(item: NewsItem) -> datetime:
    parsed, _ = _parse_timestamp(item.ingested_at)
    return parsed or datetime.now(timezone.utc)


def _item_payload(item: NewsItem) -> dict[str, Any]:
    payload = asdict(item)
    payload["source_url"] = item.source_url_value
    payload["provider_name"] = item.provider_name_value
    payload["context_only"] = True
    payload["executable_authority"] = False
    payload["schema_version"] = NEWS_SCHEMA_VERSION
    return payload


def _clean_row(item: NewsItem, validation: NewsValidation, checksum: str, raw_path: Path) -> dict[str, Any]:
    return {
        "schema_version": NEWS_SCHEMA_VERSION,
        "news_id": item.news_id,
        "instrument_id": item.instrument_id,
        "headline": item.headline,
        "source_url": item.source_url_value,
        "provider_name": item.provider_name_value,
        "published_at": item.published_at,
        "ingested_at": item.ingested_at,
        "instrument_mapping_method": item.instrument_mapping_method,
        "available_at_decision_time": validation.available_at_decision_time,
        "timestamp_confidence": validation.timestamp_confidence,
        "timestamp_status": validation.status,
        "backtest_eligible": validation.backtest_eligible,
        "credibility": item.credibility,
        "source_authority": item.source,
        "context_only": True,
        "executable_authority": False,
        "raw_path": str(raw_path),
        "item_checksum": checksum,
    }


def _read_clean(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(path)
        for column, default in (("context_only", True), ("executable_authority", False)):
            if column not in frame.columns:
                frame[column] = default
        frame["context_only"] = True
        frame["executable_authority"] = False
        return frame
    except Exception:
        return pd.DataFrame()


def _read_clean_strict(path: Path) -> pd.DataFrame:
    """Read an existing canonical ledger, rejecting unreadable generations."""

    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise ValueError(f"Canonical news ledger cannot be read: {path}") from exc
    # A readable Parquet file is not necessarily a canonical news ledger.
    # Require the fields needed to revalidate point-in-time provenance and
    # authority before appending a new generation.  A small set of aliases is
    # accepted for ledgers produced by earlier writers, but authority fields
    # themselves are never defaulted on the strict path.
    required_groups = (
        ("schema_version",),
        ("news_id",),
        ("item_checksum",),
        ("published_at",),
        ("ingested_at",),
        ("available_at_decision_time",),
        ("backtest_eligible",),
        ("context_only",),
        ("executable_authority",),
        ("timestamp_confidence", "timestamp_status"),
        ("instrument_id",),
        ("instrument_mapping_method",),
        ("source_url", "url"),
        ("provider_name", "provider"),
        ("source_authority", "source"),
        ("raw_path",),
    )
    missing = ["/".join(group) for group in required_groups if not set(group).intersection(frame.columns)]
    if missing:
        raise ValueError(f"Canonical news ledger has unsupported schema; missing: {', '.join(missing)}")
    frame["context_only"] = True
    frame["executable_authority"] = False
    return frame


def _payload_checksum(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in str(value)) or "unknown"


persist_news = persist_news_items
write_news_items = persist_news_items


__all__ = [
    "NEWS_CLEAN_PATH",
    "NEWS_RAW_DIR",
    "NEWS_SCHEMA_VERSION",
    "NewsItem",
    "NewsPersistenceResult",
    "NewsValidation",
    "build_news_contradiction_rows",
    "CONTRADICTION_RULES",
    "ContradictionResult",
    "build_news_macro_contradictions",
    "evaluate_news_macro_contradictions",
    "build_contradiction_results",
    "load_news_items",
    "persist_news_items",
    "persist_news",
    "sort_news_items",
    "write_news_items",
    "validate_news_item",
]
