import hashlib
from datetime import date

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.data import provenance
from etf_cockpit.data.provenance import sha256_dataframe


def _old_digest(frame: pd.DataFrame) -> str:
    """The digest before the speed change: the oracle every stored checksum was made with."""
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    stable = frame.copy()
    for column in stable.columns:
        stable[column] = stable[column].astype(str)
    return hashlib.sha256(stable.sort_index(axis=1).to_csv(index=False).encode("utf-8")).hexdigest()


def _edge_frame(rows: int = 40) -> pd.DataFrame:
    index = np.arange(rows)
    floats = np.array([0.0, -0.0, 1e-4, 1e-5, 1e15, 1e16, 0.1, np.nan, np.inf, -np.inf, 5e-324, 123.456])
    stamps = pd.to_datetime("2024-01-01") + pd.to_timedelta(index % 3, unit="D")
    return pd.DataFrame({
        "z_float": floats[index % len(floats)],
        "a_int": index % 4,
        "flag": index % 2 == 0,
        "nullable": pd.array([None if i % 5 == 0 else i % 3 for i in index], dtype="Int64"),
        "mixed": pd.Series([[None, np.nan, 1, True, 1.0, "x"][i % 6] for i in index], dtype=object),
        "day": [date(2024, 1, 1 + i % 3) for i in index],
        "midnight": stamps,
        "with_time": stamps + pd.to_timedelta(index % 2, unit="h"),
        "tz": (stamps + pd.to_timedelta(index % 2, unit="ns")).tz_localize("Europe/Amsterdam"),
        "nat": pd.Series(stamps).where(index % 4 != 0),
        "span": pd.to_timedelta(index % 3, unit="D"),
        "cat": pd.Categorical([["b", "a"][i % 2] for i in index]),
        "text": pd.array([None if i % 7 == 0 else f"t{i % 3}" for i in index], dtype="string"),
    })


def test_digest_equals_the_old_digest_on_edge_values():
    frame = _edge_frame()
    assert sha256_dataframe(frame) == _old_digest(frame)
    assert sha256_dataframe(frame[frame.columns[::-1]]) == _old_digest(frame)  # column order is not seen


@pytest.mark.parametrize("value", ["a,b", 'say "x"', "line\nbreak", "cr\rx", ""])
def test_digest_equals_the_old_digest_when_csv_quotes(value):
    frame = pd.DataFrame({"id": ["x", value, "y"], "v": [1.0, 2.0, 3.0]})
    assert sha256_dataframe(frame) == _old_digest(frame)
    assert sha256_dataframe(frame.rename(columns={"v": value or "e"})) == _old_digest(frame.rename(columns={"v": value or "e"}))


def test_digest_equals_the_old_digest_over_chunks(monkeypatch):
    # The text of a datetime column depends on all its values (dates only, resolution), not on one chunk's.
    monkeypatch.setattr(provenance, "_DIGEST_CHUNK_ROWS", 4)
    frame = _edge_frame(41)
    frame.loc[40, "midnight"] = pd.Timestamp("2024-01-05 00:00:00.000001")
    assert sha256_dataframe(frame) == _old_digest(frame)
    assert sha256_dataframe(frame.iloc[0:0]) == _old_digest(frame.iloc[0:0])
