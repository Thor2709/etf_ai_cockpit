"""Point-in-time, context-only macro scenario evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import re
from typing import Mapping, Sequence


MACRO_SCENARIO_CONTRACT = "macro-scenario-context.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MacroScenarioError(ValueError):
    """Raised when macro scenario evidence violates its authority contract."""


class MacroAuthority(str, Enum):
    OFFICIAL_PUBLIC_FILE = "official_public_file"
    LOCAL_USER_IMPORT = "local_user_import"


@dataclass(frozen=True)
class MacroEvidence:
    evidence_id: str
    driver: str
    series_id: str
    country: str
    currency: str
    unit: str
    value: float
    observation_time: str
    effective_time: str
    available_at: str
    revision: int
    source_id: str
    source_sha256: str
    authority: MacroAuthority
    limitations: tuple[str, ...] = ()
    execution_allowed: bool = False


@dataclass(frozen=True)
class MacroScenarioLink:
    link_id: str
    scenario: str
    driver: str
    series_id: str
    country: str
    currency: str
    unit: str
    horizon_days: int
    rationale: str
    user_authored: bool = True
    execution_allowed: bool = False


@dataclass(frozen=True)
class MacroScenarioRow:
    link_id: str
    scenario: str
    driver: str
    series_id: str
    status: str
    reason_codes: tuple[str, ...]
    value: float | None
    country: str
    currency: str
    unit: str
    horizon_days: int
    evidence_id: str | None
    observation_time: str | None
    effective_time: str | None
    available_at: str | None
    revision: int | None
    source_id: str | None
    source_sha256: str | None
    authority: str | None
    candidate_evidence_ids: tuple[str, ...]
    confidence: float
    rationale: str
    context_only: bool = True
    score_eligible: bool = False
    forecast_authority: bool = False
    execution_allowed: bool = False


@dataclass(frozen=True)
class MacroScenarioContext:
    contract: str
    status: str
    decision_time: str
    portfolio_currency: str
    horizon_days: int
    rows: tuple[MacroScenarioRow, ...]
    limitations: tuple[str, ...]
    context_hash: str
    context_only: bool = True
    score_eligible: bool = False
    forecast_authority: bool = False
    execution_allowed: bool = False


def build_macro_scenario_context(
    evidence: Sequence[MacroEvidence],
    links: Sequence[MacroScenarioLink],
    *,
    decision_time: str,
    portfolio_currency: str,
    horizon_days: int,
) -> MacroScenarioContext:
    """Build deterministic scenario context using only evidence known at the cutoff."""
    decision = _time(decision_time)
    currency = _text(portfolio_currency, "portfolio currency").upper()
    if horizon_days <= 0:
        raise MacroScenarioError("horizon_days must be positive")
    if len({link.link_id for link in links}) != len(links):
        raise MacroScenarioError("link_id must be unique")

    rows = tuple(
        _build_row(link, evidence, decision, currency, horizon_days)
        for link in sorted(links, key=lambda item: (item.scenario, item.driver, item.link_id))
    )
    limitations = tuple(
        sorted({reason for row in rows for reason in row.reason_codes if row.status != "available"})
    )
    available = sum(row.status == "available" for row in rows)
    status = "available" if rows and available == len(rows) else "partial" if available else "unavailable"
    provisional = {
        "contract": MACRO_SCENARIO_CONTRACT,
        "status": status,
        "decision_time": _iso(decision),
        "portfolio_currency": currency,
        "horizon_days": horizon_days,
        "rows": rows,
        "limitations": limitations,
        "context_only": True,
        "score_eligible": False,
        "forecast_authority": False,
        "execution_allowed": False,
    }
    return MacroScenarioContext(**provisional, context_hash=_hash(provisional))


def macro_scenario_payload(context: MacroScenarioContext) -> dict[str, object]:
    return asdict(context)


def macro_scenario_hash(value: MacroScenarioContext | Mapping[str, object]) -> str:
    payload = macro_scenario_payload(value) if isinstance(value, MacroScenarioContext) else dict(value)
    payload.pop("context_hash", None)
    return _hash(payload)


def verify_macro_scenario_context(
    value: MacroScenarioContext | Mapping[str, object],
) -> dict[str, object]:
    payload = macro_scenario_payload(value) if isinstance(value, MacroScenarioContext) else dict(value)
    if (
        set(payload) != set(MacroScenarioContext.__dataclass_fields__)
        or payload.get("contract") != MACRO_SCENARIO_CONTRACT
        or payload.get("context_hash") != macro_scenario_hash(payload)
        or _has_forbidden_authority(payload)
    ):
        raise MacroScenarioError("macro scenario context verification failed")
    return payload


def _build_row(
    link: MacroScenarioLink,
    evidence: Sequence[MacroEvidence],
    decision: datetime,
    portfolio_currency: str,
    horizon_days: int,
) -> MacroScenarioRow:
    reasons = _link_reasons(link, portfolio_currency, horizon_days)
    candidates: list[MacroEvidence] = []
    rejected: set[str] = set(reasons)
    for item in evidence:
        if item.driver != link.driver or item.series_id != link.series_id:
            continue
        item_reasons = _evidence_reasons(item, decision)
        if item_reasons:
            rejected.update(item_reasons)
            continue
        if (
            item.country != link.country
            or item.currency.upper() != link.currency.upper()
            or item.unit != link.unit
        ):
            rejected.add("evidence_context_mismatch")
            continue
        candidates.append(item)

    candidate_ids = tuple(sorted(item.evidence_id for item in candidates))
    if reasons or not candidates:
        if not candidates and not rejected:
            rejected.add("driver_evidence_absent")
        return _unavailable_row(link, tuple(sorted(rejected)), candidate_ids)

    max_revision = max(item.revision for item in candidates)
    latest = [item for item in candidates if item.revision == max_revision]
    authorities = {item.authority for item in latest}
    conflicts = {
        (
            item.value,
            item.observation_time,
            item.effective_time,
            item.available_at,
            item.source_sha256,
        )
        for item in latest
    }
    if len(authorities) == 1 and len(conflicts) > 1:
        return _unavailable_row(link, ("same_revision_conflict",), candidate_ids)
    selected = sorted(
        latest,
        key=lambda item: (
            0 if item.authority is MacroAuthority.OFFICIAL_PUBLIC_FILE else 1,
            item.available_at,
            item.evidence_id,
        ),
    )[0]
    confidence, confidence_reasons = _confidence(selected, decision)
    return MacroScenarioRow(
        link_id=link.link_id,
        scenario=link.scenario,
        driver=link.driver,
        series_id=link.series_id,
        status="available",
        reason_codes=confidence_reasons,
        value=float(selected.value),
        country=link.country,
        currency=link.currency.upper(),
        unit=link.unit,
        horizon_days=link.horizon_days,
        evidence_id=selected.evidence_id,
        observation_time=_iso(_time(selected.observation_time)),
        effective_time=_iso(_time(selected.effective_time)),
        available_at=_iso(_time(selected.available_at)),
        revision=selected.revision,
        source_id=selected.source_id,
        source_sha256=selected.source_sha256,
        authority=selected.authority.value,
        candidate_evidence_ids=candidate_ids,
        confidence=confidence,
        rationale=link.rationale,
    )


def _unavailable_row(
    link: MacroScenarioLink,
    reasons: tuple[str, ...],
    candidates: tuple[str, ...],
) -> MacroScenarioRow:
    return MacroScenarioRow(
        link_id=link.link_id,
        scenario=link.scenario,
        driver=link.driver,
        series_id=link.series_id,
        status="unavailable",
        reason_codes=reasons or ("driver_evidence_absent",),
        value=None,
        country=link.country,
        currency=link.currency.upper(),
        unit=link.unit,
        horizon_days=link.horizon_days,
        evidence_id=None,
        observation_time=None,
        effective_time=None,
        available_at=None,
        revision=None,
        source_id=None,
        source_sha256=None,
        authority=None,
        candidate_evidence_ids=candidates,
        confidence=0.0,
        rationale=link.rationale,
    )


def _link_reasons(
    link: MacroScenarioLink, portfolio_currency: str, horizon_days: int
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if link.execution_allowed or not link.user_authored:
        reasons.add("link_authority_invalid")
    for value, name in (
        (link.link_id, "link_id"),
        (link.scenario, "scenario"),
        (link.driver, "driver"),
        (link.series_id, "series_id"),
        (link.country, "country"),
        (link.currency, "currency"),
        (link.unit, "unit"),
        (link.rationale, "rationale"),
    ):
        if not isinstance(value, str) or not value.strip():
            reasons.add(f"{name}_missing")
    if link.currency.upper() != portfolio_currency:
        reasons.add("portfolio_currency_mismatch")
    if link.horizon_days != horizon_days or link.horizon_days <= 0:
        reasons.add("horizon_mismatch")
    return tuple(sorted(reasons))


def _evidence_reasons(item: MacroEvidence, decision: datetime) -> tuple[str, ...]:
    reasons: set[str] = set()
    if item.execution_allowed:
        reasons.add("evidence_authority_invalid")
    if not isinstance(item.authority, MacroAuthority):
        reasons.add("source_authority_invalid")
    for value, name in (
        (item.evidence_id, "evidence_id"),
        (item.driver, "driver"),
        (item.series_id, "series_id"),
        (item.country, "country"),
        (item.currency, "currency"),
        (item.unit, "unit"),
        (item.source_id, "source_id"),
    ):
        if not isinstance(value, str) or not value.strip():
            reasons.add(f"{name}_missing")
    if not _SHA256.fullmatch(str(item.source_sha256)):
        reasons.add("source_checksum_invalid")
    if (
        isinstance(item.value, bool)
        or not isinstance(item.value, (int, float))
        or not math.isfinite(float(item.value))
    ):
        reasons.add("value_invalid")
    if not isinstance(item.revision, int) or isinstance(item.revision, bool) or item.revision < 0:
        reasons.add("revision_invalid")
    try:
        observed = _time(item.observation_time)
        effective = _time(item.effective_time)
        available = _time(item.available_at)
    except MacroScenarioError:
        reasons.add("timestamp_invalid_or_ambiguous")
        return tuple(sorted(reasons))
    if available > decision:
        reasons.add("future_availability")
    if observed > available or effective > available:
        reasons.add("availability_precedes_observation")
    return tuple(sorted(reasons))


def _confidence(item: MacroEvidence, decision: datetime) -> tuple[float, tuple[str, ...]]:
    confidence = 1.0 if item.authority is MacroAuthority.OFFICIAL_PUBLIC_FILE else 0.85
    reasons: set[str] = set()
    age = max(0, (decision - _time(item.observation_time)).days)
    if age > 365:
        confidence *= 0.55
        reasons.add("stale_observation")
    elif age > 120:
        confidence *= 0.75
        reasons.add("aging_observation")
    if item.revision > 0:
        confidence *= 0.95
        reasons.add("revised_vintage")
    if "assumed_time" in item.limitations:
        confidence *= 0.75
        reasons.add("assumed_time")
    if item.limitations:
        confidence *= 0.9
        reasons.add("source_limitations")
    return round(confidence, 6), tuple(sorted(reasons))


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MacroScenarioError("timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MacroScenarioError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MacroScenarioError(f"{name} is required")
    return value.strip()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=lambda item: asdict(item),
        )
    except (TypeError, ValueError) as exc:
        raise MacroScenarioError("macro scenario context is not canonical JSON") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _has_forbidden_authority(value: object) -> bool:
    if isinstance(value, Mapping):
        if (
            value.get("execution_allowed") is not False
            or value.get("context_only") is False
            or value.get("score_eligible") is True
            or value.get("forecast_authority") is True
        ):
            return True
        return any(_has_forbidden_authority(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_forbidden_authority(item) for item in value)
    return False
