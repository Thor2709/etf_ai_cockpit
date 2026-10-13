"""Exact-content signatures of pandas columns, used to key read-only memoisation."""

from __future__ import annotations

import hashlib

import pandas as pd


def content_signature(values: object) -> bytes | None:
    """Digest of a column/index's exact content, or None when it cannot be hashed."""

    try:
        hashed = pd.util.hash_pandas_object(values, index=False).to_numpy()
    except (TypeError, ValueError):
        return None
    return hashlib.blake2b(hashed.tobytes(), digest_size=16).digest()


def columns_key(frame: pd.DataFrame, columns: tuple[str, ...]) -> tuple[object, ...] | None:
    """Key that changes whenever the named columns' values, dtypes or row count change.

    ``None`` (callers must then not memoise) when a column is missing, duplicated, holds
    mixed Python types, or cannot be hashed; the key also pins each column's inferred type
    so equal-looking values of different types never share an entry.
    """

    parts: list[object] = [len(frame)]
    for column in columns:
        if column not in frame.columns:
            return None
        values = frame[column]
        if not isinstance(values, pd.Series):  # duplicated column label
            return None
        kind = pd.api.types.infer_dtype(values, skipna=False)
        signature = content_signature(values)
        if kind.startswith("mixed") or signature is None:
            return None
        parts.append((column, str(values.dtype), kind, signature))
    return tuple(parts)
