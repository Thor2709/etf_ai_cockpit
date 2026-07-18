"""Deterministic local screening contracts and query evaluation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Literal

import pandas as pd


FilterOperator = Literal["eq", "min", "max"]


@dataclass(frozen=True)
class ScreenFilter:
    field: str
    operator: FilterOperator
    value: str | float

    def __post_init__(self) -> None:
        field = str(self.field).strip()
        if not field:
            raise ValueError("filter field must not be blank")
        if self.operator not in {"eq", "min", "max"}:
            raise ValueError(f"unsupported filter operator: {self.operator}")
        value: str | float
        if self.operator == "eq":
            value = str(self.value).strip().casefold()
            if not value:
                raise ValueError("categorical filter value must not be blank")
        else:
            try:
                value = float(self.value)
            except (TypeError, ValueError) as exc:
                raise ValueError("numeric filter value must be finite") from exc
            if not math.isfinite(value):
                raise ValueError("numeric filter value must be finite")
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "value", value)

    def as_dict(self) -> dict[str, object]:
        return {"field": self.field, "operator": self.operator, "value": self.value}


@dataclass(frozen=True)
class ScreenSort:
    field: str
    descending: bool = False

    def __post_init__(self) -> None:
        field = str(self.field).strip()
        if not field:
            raise ValueError("sort field must not be blank")
        object.__setattr__(self, "field", field)

    def as_dict(self) -> dict[str, object]:
        return {"field": self.field, "descending": self.descending}


@dataclass(frozen=True)
class ScreenQuery:
    filters: tuple[ScreenFilter, ...] = ()
    sort: tuple[ScreenSort, ...] = ()
    requested_fields: tuple[str, ...] = ()
    as_of: str = "unavailable"
    universe_revision: str = "unavailable"
    formula_version: str = "unavailable"
    formula_checksum: str = "unavailable"
    input_checksum: str = "unavailable"
    dataset_checksums: tuple[tuple[str, str], ...] = ()
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        requested = tuple(dict.fromkeys(str(field).strip() for field in self.requested_fields if str(field).strip()))
        checksums = tuple(sorted((str(key).strip(), str(value).strip()) for key, value in self.dataset_checksums if str(key).strip()))
        object.__setattr__(self, "requested_fields", requested)
        object.__setattr__(self, "dataset_checksums", checksums)
        object.__setattr__(self, "as_of", str(self.as_of or "unavailable"))
        object.__setattr__(self, "universe_revision", str(self.universe_revision or "unavailable"))
        object.__setattr__(self, "formula_version", str(self.formula_version or "unavailable"))
        object.__setattr__(self, "formula_checksum", str(self.formula_checksum or "unavailable"))
        object.__setattr__(self, "input_checksum", str(self.input_checksum or "unavailable"))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "filters": [item.as_dict() for item in self.filters],
            "sort": [item.as_dict() for item in self.sort],
            "requested_fields": list(self.requested_fields),
            "as_of": self.as_of,
            "universe_revision": self.universe_revision,
            "formula_version": self.formula_version,
            "formula_checksum": self.formula_checksum,
            "input_checksum": self.input_checksum,
            "dataset_checksums": {key: value for key, value in self.dataset_checksums},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ScreenQuery:
        allowed = {
            "schema_version", "filters", "sort", "requested_fields", "as_of",
            "universe_revision", "formula_version", "formula_checksum", "dataset_checksums",
            "input_checksum",
        }
        if set(payload) - allowed:
            raise ValueError("screen query contains unknown fields")
        if payload.get("schema_version") != "1.0":
            raise ValueError("unsupported screen query schema version")
        for key in ("as_of", "universe_revision", "formula_version", "formula_checksum", "input_checksum"):
            if key in payload and not isinstance(payload[key], str):
                raise ValueError(f"screen query {key} must be text")
        filters = tuple(
            _filter_from_dict(item)
            for item in _mapping_items(payload.get("filters"), field="filters")
        )
        sort = tuple(
            _sort_from_dict(item)
            for item in _mapping_items(payload.get("sort"), field="sort")
        )
        checksums = payload.get("dataset_checksums")
        if not isinstance(checksums, Mapping) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in checksums.items()):
            raise ValueError("screen query dataset_checksums must be a text mapping")
        checksum_items = tuple((key, value) for key, value in checksums.items())
        requested = payload.get("requested_fields")
        if not isinstance(requested, list) or any(not isinstance(item, str) for item in requested):
            raise ValueError("screen query requested_fields must be a text list")
        return cls(
            filters=filters,
            sort=sort,
            requested_fields=tuple(requested),
            as_of=str(payload.get("as_of") or "unavailable"),
            universe_revision=str(payload.get("universe_revision") or "unavailable"),
            formula_version=str(payload.get("formula_version") or "unavailable"),
            formula_checksum=str(payload.get("formula_checksum") or "unavailable"),
            input_checksum=str(payload.get("input_checksum") or "unavailable"),
            dataset_checksums=checksum_items,
            schema_version=str(payload.get("schema_version") or "1.0"),
        )

    @property
    def checksum(self) -> str:
        encoded = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ScreenResult:
    rows: tuple[dict[str, object], ...]
    total_input: int
    total_matched: int
    available_fields: tuple[str, ...]
    unavailable_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    query_checksum: str
    input_checksum: str
    execution_allowed: Literal[False] = False

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([dict(row) for row in self.rows])


def run_screen(records: pd.DataFrame | Iterable[Mapping[str, object]], query: ScreenQuery) -> ScreenResult:
    """Apply a typed query without providers, models, persistence or authority."""

    rows = _records(records)
    input_checksum = records_checksum(rows)
    available = tuple(sorted({str(field) for row in rows for field in row}))
    requested = {
        *(item.field for item in query.filters),
        *(item.field for item in query.sort),
        *query.requested_fields,
    }
    unavailable = tuple(sorted(field for field in requested if field not in available))
    warnings = tuple(f"unavailable_field:{field}" for field in unavailable)

    matched = rows
    for condition in query.filters:
        if condition.field in unavailable:
            matched = []
            break
        matched = [row for row in matched if _matches(row.get(condition.field), condition)]
    for ordering in reversed(query.sort):
        if ordering.field not in available:
            continue
        values = [_number(row.get(ordering.field)) for row in matched]
        numeric = any(value is not None for value in values)
        present = [
            row
            for row in matched
            if _sort_value(row.get(ordering.field), numeric=numeric) is not None
        ]
        missing = [
            row
            for row in matched
            if _sort_value(row.get(ordering.field), numeric=numeric) is None
        ]
        present.sort(
            key=lambda row: _sort_value(row.get(ordering.field), numeric=numeric),
            reverse=ordering.descending,
        )
        matched = present + missing

    return ScreenResult(
        rows=tuple(dict(row) for row in matched),
        total_input=len(rows),
        total_matched=len(matched),
        available_fields=available,
        unavailable_fields=unavailable,
        warnings=warnings,
        query_checksum=query.checksum,
        input_checksum=input_checksum,
    )


def bind_query(
    records: pd.DataFrame | Iterable[Mapping[str, object]],
    query: ScreenQuery,
) -> ScreenQuery:
    """Return a query explicitly bound to the canonical input row digest."""

    return replace(query, input_checksum=records_checksum(records))


def records_checksum(records: pd.DataFrame | Iterable[Mapping[str, object]]) -> str:
    rows = _records(records)
    canonical = [
        {str(key): None if _missing(value) else value for key, value in row.items()}
        for row in rows
    ]
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping_items(value: object, *, field: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"screen query {field} must be a list")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError("screen query entries must be mappings")
    return tuple(item for item in value if isinstance(item, Mapping))


def _filter_from_dict(item: Mapping[str, object]) -> ScreenFilter:
    if set(item) != {"field", "operator", "value"}:
        raise ValueError("screen filter fields are invalid")
    if not isinstance(item["field"], str) or not isinstance(item["operator"], str):
        raise ValueError("screen filter field and operator must be text")
    value = item["value"]
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("screen filter value has an invalid type")
    return ScreenFilter(item["field"], item["operator"], value)  # type: ignore[arg-type]


def _sort_from_dict(item: Mapping[str, object]) -> ScreenSort:
    if set(item) != {"field", "descending"}:
        raise ValueError("screen sort fields are invalid")
    if not isinstance(item["field"], str) or not isinstance(item["descending"], bool):
        raise ValueError("screen sort field and direction have invalid types")
    return ScreenSort(item["field"], item["descending"])


def _records(records: pd.DataFrame | Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    if isinstance(records, pd.DataFrame):
        return [dict(row) for row in records.to_dict(orient="records")]
    return [dict(row) for row in records]


def _matches(value: object, condition: ScreenFilter) -> bool:
    if condition.operator == "eq":
        return _text(value) == _text(condition.value)
    number = _number(value)
    if number is None:
        return False
    boundary = float(condition.value)
    return number >= boundary if condition.operator == "min" else number <= boundary


def _text(value: object) -> str:
    return "" if _missing(value) else str(value).strip().casefold()


def _number(value: object) -> float | None:
    if _missing(value):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sort_value(value: object, *, numeric: bool) -> float | str | None:
    if _missing(value):
        return None
    number = _number(value)
    if numeric:
        return number
    return str(value).strip().casefold()


def _missing(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


__all__ = [
    "FilterOperator",
    "ScreenFilter",
    "ScreenQuery",
    "ScreenResult",
    "ScreenSort",
    "bind_query",
    "records_checksum",
    "run_screen",
]
