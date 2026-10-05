"""JSON-safe, deterministic serialisation of calculation outputs for the parity goldens.

Missing values stay explicit and distinct: ``None`` for None/pd.NA/NaT, the string ``"<NaN>"`` for a float NaN,
``"<inf>"``/``"<-inf>"`` for infinities.  Nothing is ever zero-filled.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import date, datetime, time
from enum import Enum
from decimal import Decimal
from pathlib import PurePath

import numpy as np
import pandas as pd

from refactor_parity._harness import FLOAT_ABS

NAN = "<NaN>"
POS_INF = "<inf>"
NEG_INF = "<-inf>"
# Digits kept when decimal literals inside strings are normalised before hashing (documented default).
STRING_FLOAT_DIGITS = 6
SAMPLE_ROWS = 3
_FLOAT_IN_TEXT = re.compile(r"-?\d+\.\d+(?:[eE][+-]?\d+)?")
# sha256 digests derive from float text, which is not bit-stable across platforms (libm), so every 64-hex string
# in a pipeline golden is masked; the mask keeps "a digest was present" explicit.
_SHA256 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
SHA256_MASK = "<sha256>"


def _float(value: float) -> object:
    if math.isnan(value):
        return NAN
    if math.isinf(value):
        return POS_INF if value > 0 else NEG_INF
    return float(value)


def jsonable(value: object) -> object:
    """Recursively convert ``value`` to JSON-safe primitives (dict order preserved, sets sorted)."""

    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Enum):
        return jsonable(value.value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return _float(float(value))
    if isinstance(value, str):
        return value
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, pd.DataFrame):
        return {"columns": [str(column) for column in value.columns], "rows": [jsonable(row) for row in value.to_dict("records")]}
    if isinstance(value, pd.Series):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((jsonable(item) for item in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return {str(key): jsonable(item) for key, item in vars(value).items() if not str(key).startswith("_")}
    return repr(value)


def _normalise_text(text: str) -> str:
    text = _SHA256.sub(SHA256_MASK, text)
    return _FLOAT_IN_TEXT.sub(lambda match: f"{float(match.group(0)):.{STRING_FLOAT_DIGITS}f}", text)


def mask_digests(value: object) -> object:
    """Replace every sha256 hex digest (anywhere inside a string) in an already-jsonable structure."""

    if isinstance(value, str):
        return _SHA256.sub(SHA256_MASK, value)
    if isinstance(value, dict):
        return {key: mask_digests(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_digests(item) for item in value]
    return value


def _is_float_column(series: pd.Series) -> bool:
    return pd.api.types.is_float_dtype(series.dtype)


def frame_golden(
    frame: pd.DataFrame, *, sample_rows: int = SAMPLE_ROWS, exclude_columns: tuple[str, ...] = ()
) -> dict[str, object]:
    """Shape, columns, dtypes, per-numeric-column aggregates, first/last rows and an exact hash of the rest.

    * numeric columns: NaN count and sum/mean/min/max (compared approximately by the test);
    * every other column (strings, dates, booleans, objects): hashed exactly after decimal literals inside the
      text are normalised to ``STRING_FLOAT_DIGITS`` places (cross-platform last-bit float noise);
    * ``first_rows``/``last_rows`` keep the full row values for a readable diff.
    """

    excluded = [column for column in exclude_columns if column in frame.columns]
    frame = frame.drop(columns=excluded)
    columns = [str(column) for column in frame.columns]
    numeric: dict[str, object] = {}
    digest = hashlib.sha256()
    for column in frame.columns:
        series = frame[column]
        numeric_kind = pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype)
        if numeric_kind:
            values = pd.to_numeric(series, errors="coerce").astype("float64")
            finite = values[np.isfinite(values)]
            numeric[str(column)] = {
                "nan_count": int(values.isna().sum()),
                "count": int(finite.size),
                "sum": jsonable(float(finite.sum())) if finite.size else None,
                "mean": jsonable(float(finite.mean())) if finite.size else None,
                "min": jsonable(float(finite.min())) if finite.size else None,
                "max": jsonable(float(finite.max())) if finite.size else None,
            }
            if not _is_float_column(series):
                digest.update(f"{column}:{'|'.join(str(item) for item in series.tolist())}".encode())
            continue
        digest.update(str(column).encode())
        for item in series.tolist():
            digest.update(b"\x00" + _normalise_text(str(jsonable(item))).encode())
    head = frame.head(sample_rows)
    tail = frame.tail(sample_rows) if len(frame) > sample_rows else frame.iloc[0:0]
    return {
        "excluded_columns": excluded,
        "shape": [int(frame.shape[0]), int(frame.shape[1])],
        "columns": columns,
        "dtypes": {str(column): str(dtype) for column, dtype in frame.dtypes.items()},
        "numeric_columns": numeric,
        "non_float_digest": digest.hexdigest(),
        "first_rows": [mask_digests(jsonable(row)) for row in head.to_dict("records")],
        "last_rows": [mask_digests(jsonable(row)) for row in tail.to_dict("records")],
    }


LARGE_LIST_LIMIT = 50
# Floats inside a compacted list are hashed at 8 significant digits (relative 1e-8, a decade coarser than the
# harness FLOAT_REL of 1e-9 so a rounding-boundary flip from last-bit noise is improbable); |x| < FLOAT_ABS is 0.0.
LIST_FLOAT_SIGNIFICANT_DIGITS = 8
FIELD_DIGEST_HEX = 16
_MISSING_KEY = ["m"]


def _canonical(value: object) -> object:
    """Injective, tagged canonical form of an already-jsonable value used only for list digests.

    Floats: ``|x| < FLOAT_ABS`` (including -0.0) becomes 0.0, every other float keeps
    ``LIST_FLOAT_SIGNIFICANT_DIGITS`` significant digits, so last-bit libm/SIMD noise (also on extreme magnitudes
    such as 3e17, where six decimal places are ~23 significant digits) cannot change the digest while a relative
    change of 1e-6 still does.  Strings keep the sha256 mask and 6-place text decimals.  Every node is a tagged
    list, so a float, a string, an int and a container can never collide.
    """

    if value is None:
        return ["n"]
    if isinstance(value, bool):
        return ["b", value]
    if isinstance(value, int):
        return ["i", value]
    if isinstance(value, float):
        return ["f", f"{0.0 if abs(value) < FLOAT_ABS else value:.{LIST_FLOAT_SIGNIFICANT_DIGITS - 1}e}"]
    if isinstance(value, str):
        return ["s", _normalise_text(value)]
    if isinstance(value, list):
        return ["l", [_canonical(item) for item in value]]
    if isinstance(value, dict):
        return ["d", [[str(key), _canonical(value[key])] for key in sorted(value, key=str)]]
    raise TypeError(f"not a jsonable value: {type(value).__name__}")


def _digest(canonical: object, hex_length: int) -> str:
    text = json.dumps(canonical, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:hex_length]


def compact_large_lists(value: object, *, limit: int = LARGE_LIST_LIMIT) -> object:
    """Replace every list longer than ``limit`` by length, first/last item and a content digest.

    ``digest32`` is a 32-hex prefix of a sha256 over the canonical form of the list (see ``_canonical``): exact for
    strings/ints/booleans/None, platform-stable for floats (|x| < FLOAT_ABS folded to 0.0, otherwise 8 significant
    digits).  When every item is a dict, ``field_digests`` adds one 16-hex digest per key (over that key's column,
    a missing key being distinct from None) so a mismatch names the field(s).
    """

    if isinstance(value, dict):
        return {key: compact_large_lists(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) <= limit:
            return [compact_large_lists(item, limit=limit) for item in value]
        compact: dict[str, object] = {
            "list_length": len(value),
            "digest32": _digest(_canonical(value), 32),
        }
        if all(isinstance(item, dict) for item in value):
            keys = sorted({str(key) for item in value for key in item})
            compact["field_digests"] = {
                key: _digest([_canonical(item[key]) if key in item else _MISSING_KEY for item in value], FIELD_DIGEST_HEX)
                for key in keys
            }
        compact["first_item"] = compact_large_lists(value[0], limit=limit)
        compact["last_item"] = compact_large_lists(value[-1], limit=limit)
        return compact
    return value
