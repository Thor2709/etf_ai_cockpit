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
_ROW_REASONS = frozenset(
    {
        "aging_observation",
        "assumed_time",
        "availability_precedes_observation",
        "country_missing",
        "currency_missing",
        "driver_evidence_absent",
        "driver_missing",
        "evidence_authority_invalid",
        "evidence_context_mismatch",
        "evidence_id_missing",
        "future_availability",
        "horizon_mismatch",
        "link_authority_invalid",
        "link_id_missing",
        "portfolio_currency_mismatch",
        "rationale_missing",
        "revised_vintage",
        "revision_invalid",
        "same_revision_conflict",
        "scenario_missing",
        "series_id_missing",
        "source_authority_invalid",
        "source_checksum_invalid",
        "source_id_missing",
        "source_limitations",
        "stale_observation",
        "timestamp_invalid_or_ambiguous",
        "unit_missing",
        "value_invalid",
    }
)


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
    try:
        rebuilt = _rebuild_context(payload)
    except (KeyError, TypeError, ValueError, MacroScenarioError) as exc:
        raise MacroScenarioError("macro scenario context verification failed") from exc
    canonical = macro_scenario_payload(rebuilt)
    if _normalise_json(payload) != _normalise_json(canonical):
        raise MacroScenarioError("macro scenario context verification failed")
    return canonical


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

    latest_period = max(
        (_time(item.effective_time), _time(item.observation_time)) for item in candidates
    )
    period_candidates = [
        item
        for item in candidates
        if (_time(item.effective_time), _time(item.observation_time)) == latest_period
    ]
    max_revision = max(item.revision for item in period_candidates)
    latest = [item for item in period_candidates if item.revision == max_revision]
    conflicts_by_authority = {
        authority: {
            (
                item.value,
                item.observation_time,
                item.effective_time,
                item.available_at,
                item.source_sha256,
            )
            for item in latest
            if item.authority is authority
        }
        for authority in MacroAuthority
    }
    if any(len(conflicts) > 1 for conflicts in conflicts_by_authority.values()):
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


def _rebuild_context(payload: Mapping[str, object]) -> MacroScenarioContext:
    if set(payload) != set(MacroScenarioContext.__dataclass_fields__):
        raise MacroScenarioError("context schema is invalid")
    contract = _strict_str(payload["contract"])
    status = _strict_str(payload["status"])
    decision_time = _strict_str(payload["decision_time"])
    portfolio_currency = _strict_str(payload["portfolio_currency"])
    horizon_days = _strict_int(payload["horizon_days"])
    context_hash = _strict_str(payload["context_hash"])
    if (
        contract != MACRO_SCENARIO_CONTRACT
        or status not in {"available", "partial", "unavailable"}
        or decision_time != _iso(_time(decision_time))
        or portfolio_currency != portfolio_currency.upper()
        or horizon_days <= 0
        or not _SHA256.fullmatch(context_hash)
    ):
        raise MacroScenarioError("context values are invalid")
    context_only = _strict_bool(payload["context_only"])
    score_eligible = _strict_bool(payload["score_eligible"])
    forecast_authority = _strict_bool(payload["forecast_authority"])
    execution_allowed = _strict_bool(payload["execution_allowed"])
    if not context_only or score_eligible or forecast_authority or execution_allowed:
        raise MacroScenarioError("context authority is invalid")

    decision = _time(decision_time)
    rows_raw = _strict_sequence(payload["rows"])
    rows = tuple(_rebuild_row(row, decision) for row in rows_raw)
    if rows != tuple(sorted(rows, key=lambda row: (row.scenario, row.driver, row.link_id))):
        raise MacroScenarioError("rows are not canonically ordered")
    if len({row.link_id for row in rows}) != len(rows):
        raise MacroScenarioError("row link identity is duplicated")
    if any(
        row.currency != portfolio_currency or row.horizon_days != horizon_days
        for row in rows
    ):
        raise MacroScenarioError("row context differs from the declared portfolio context")
    limitations = _strict_str_tuple(payload["limitations"])
    derived_limitations = tuple(
        sorted({reason for row in rows for reason in row.reason_codes if row.status != "available"})
    )
    available = sum(row.status == "available" for row in rows)
    derived_status = (
        "available"
        if rows and available == len(rows)
        else "partial"
        if available
        else "unavailable"
    )
    if limitations != derived_limitations or status != derived_status:
        raise MacroScenarioError("derived context fields are inconsistent")
    provisional = {
        "contract": contract,
        "status": status,
        "decision_time": decision_time,
        "portfolio_currency": portfolio_currency,
        "horizon_days": horizon_days,
        "rows": rows,
        "limitations": limitations,
        "context_only": context_only,
        "score_eligible": score_eligible,
        "forecast_authority": forecast_authority,
        "execution_allowed": execution_allowed,
    }
    rebuilt = MacroScenarioContext(**provisional, context_hash=context_hash)
    if context_hash != _hash(provisional) or _has_forbidden_authority(asdict(rebuilt)):
        raise MacroScenarioError("context hash or authority is invalid")
    return rebuilt


def _rebuild_row(value: object, decision: datetime) -> MacroScenarioRow:
    if not isinstance(value, Mapping) or set(value) != set(MacroScenarioRow.__dataclass_fields__):
        raise MacroScenarioError("row schema is invalid")
    status = _strict_str(value["status"])
    if status not in {"available", "unavailable"}:
        raise MacroScenarioError("row status is invalid")
    reasons = _strict_str_tuple(value["reason_codes"])
    if reasons != tuple(sorted(set(reasons))) or not set(reasons) <= _ROW_REASONS:
        raise MacroScenarioError("row reasons are invalid")
    candidates = _strict_str_tuple(value["candidate_evidence_ids"])
    if candidates != tuple(sorted(set(candidates))):
        raise MacroScenarioError("candidate evidence is not canonical")
    confidence = _strict_float(value["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise MacroScenarioError("confidence is invalid")
    row = MacroScenarioRow(
        link_id=_strict_str(value["link_id"]),
        scenario=_strict_str(value["scenario"]),
        driver=_strict_str(value["driver"]),
        series_id=_strict_str(value["series_id"]),
        status=status,
        reason_codes=reasons,
        value=_strict_optional_float(value["value"]),
        country=_strict_str(value["country"]),
        currency=_strict_str(value["currency"]),
        unit=_strict_str(value["unit"]),
        horizon_days=_strict_int(value["horizon_days"]),
        evidence_id=_strict_optional_str(value["evidence_id"]),
        observation_time=_strict_optional_str(value["observation_time"]),
        effective_time=_strict_optional_str(value["effective_time"]),
        available_at=_strict_optional_str(value["available_at"]),
        revision=_strict_optional_int(value["revision"]),
        source_id=_strict_optional_str(value["source_id"]),
        source_sha256=_strict_optional_str(value["source_sha256"]),
        authority=_strict_optional_str(value["authority"]),
        candidate_evidence_ids=candidates,
        confidence=confidence,
        rationale=_strict_str(value["rationale"]),
        context_only=_strict_bool(value["context_only"]),
        score_eligible=_strict_bool(value["score_eligible"]),
        forecast_authority=_strict_bool(value["forecast_authority"]),
        execution_allowed=_strict_bool(value["execution_allowed"]),
    )
    if (
        row.horizon_days <= 0
        or row.currency != row.currency.upper()
        or not row.context_only
        or row.score_eligible
        or row.forecast_authority
        or row.execution_allowed
    ):
        raise MacroScenarioError("row authority or context is invalid")
    lineage = (
        row.evidence_id,
        row.observation_time,
        row.effective_time,
        row.available_at,
        row.revision,
        row.source_id,
        row.source_sha256,
        row.authority,
    )
    if row.status == "available":
        observed = _time(row.observation_time or "")
        effective = _time(row.effective_time or "")
        available = _time(row.available_at or "")
        if (
            row.value is None
            or any(item is None for item in lineage)
            or row.confidence <= 0
            or row.authority not in {item.value for item in MacroAuthority}
            or not _SHA256.fullmatch(row.source_sha256 or "")
            or row.evidence_id not in row.candidate_evidence_ids
            or row.observation_time != _iso(observed)
            or row.effective_time != _iso(effective)
            or row.available_at != _iso(available)
            or available > decision
            or observed > available
            or effective > available
            or row.revision is None
            or row.revision < 0
        ):
            raise MacroScenarioError("available row lineage is invalid")
        expected_reasons: set[str] = set()
        expected_confidence = (
            1.0
            if row.authority == MacroAuthority.OFFICIAL_PUBLIC_FILE.value
            else 0.85
        )
        age = max(0, (decision - observed).days)
        if age > 365:
            expected_confidence *= 0.55
            expected_reasons.add("stale_observation")
        elif age > 120:
            expected_confidence *= 0.75
            expected_reasons.add("aging_observation")
        if row.revision > 0:
            expected_confidence *= 0.95
            expected_reasons.add("revised_vintage")
        if "assumed_time" in reasons:
            expected_confidence *= 0.75
            expected_reasons.add("assumed_time")
        if "source_limitations" in reasons:
            expected_confidence *= 0.9
            expected_reasons.add("source_limitations")
        if "assumed_time" in reasons and "source_limitations" not in reasons:
            raise MacroScenarioError("assumed time must remain a source limitation")
        if reasons != tuple(sorted(expected_reasons)) or confidence != round(
            expected_confidence, 6
        ):
            raise MacroScenarioError("available row confidence is inconsistent")
    elif (
        row.value is not None
        or any(item is not None for item in lineage)
        or row.confidence != 0.0
        or not row.reason_codes
    ):
        raise MacroScenarioError("unavailable row must fail closed")
    return row


def _strict_sequence(value: object) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise MacroScenarioError("sequence is invalid")
    return tuple(value)


def _strict_str_tuple(value: object) -> tuple[str, ...]:
    return tuple(_strict_str(item) for item in _strict_sequence(value))


def _strict_str(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise MacroScenarioError("string is invalid")
    return value


def _strict_optional_str(value: object) -> str | None:
    return None if value is None else _strict_str(value)


def _strict_bool(value: object) -> bool:
    if type(value) is not bool:
        raise MacroScenarioError("boolean is invalid")
    return value


def _strict_int(value: object) -> int:
    if type(value) is not int:
        raise MacroScenarioError("integer is invalid")
    return value


def _strict_optional_int(value: object) -> int | None:
    return None if value is None else _strict_int(value)


def _strict_float(value: object) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise MacroScenarioError("float is invalid")
    return value


def _strict_optional_float(value: object) -> float | None:
    return None if value is None else _strict_float(value)


def _normalise_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _normalise_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise_json(item) for item in value]
    return value


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
