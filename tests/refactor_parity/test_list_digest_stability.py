"""Self-test of the compacted-list digest used by the parity goldens (platform stability vs detection strength)."""

from __future__ import annotations

import math

import pytest
from refactor_parity._harness import FLOAT_ABS
from refactor_parity._serialise import LARGE_LIST_LIMIT, compact_large_lists

COST = 3.173172108128448e17


def _rows() -> list[dict[str, object]]:
    return [
        {"id": f"row-{index}", "count": index, "cost": COST + index * 1e12, "tiny": 1e-14 * index, "note": "ok 1.5"}
        for index in range(LARGE_LIST_LIMIT + 5)
    ]


def _compact(rows: list[dict[str, object]]) -> dict[str, object]:
    compacted = compact_large_lists(rows)
    assert isinstance(compacted, dict)
    return compacted


def _changed_fields(left: dict[str, object], right: dict[str, object]) -> set[str]:
    left_fields, right_fields = left["field_digests"], right["field_digests"]
    return {key for key in left_fields if left_fields[key] != right_fields[key]}  # type: ignore[union-attr]


def test_digest_ignores_one_ulp_and_sub_abs_sign_flips() -> None:
    base = _compact(_rows())
    rows = _rows()
    rows[7]["cost"] = math.nextafter(float(rows[7]["cost"]), math.inf)  # type: ignore[arg-type]
    rows[-1]["cost"] = math.nextafter(float(rows[-1]["cost"]), -math.inf)  # type: ignore[arg-type]
    rows[3]["tiny"] = -0.4 * FLOAT_ABS
    rows[4]["tiny"] = -0.0
    perturbed = _compact(rows)
    # first_item/last_item are compared by the harness with the float tolerance; only the digests must be identical.
    assert perturbed["digest32"] == base["digest32"] and perturbed["field_digests"] == base["field_digests"]


def test_digest_detects_relative_1e6_string_and_int_changes_and_names_only_that_field() -> None:
    base = _compact(_rows())
    for key, mutate in (
        ("cost", lambda value: float(value) * (1 + 1e-6)),
        ("tiny", lambda value: 1e-9),
        ("note", lambda value: "ok 1.6"),
        ("id", lambda value: "row-x"),
        ("count", lambda value: int(value) + 1),
    ):
        rows = _rows()
        rows[10][key] = mutate(rows[10][key])
        changed = _compact(rows)
        assert changed["digest32"] != base["digest32"], key
        assert _changed_fields(base, changed) == {key}, key


def test_digest_distinguishes_missing_key_none_and_value_types() -> None:
    base = _compact(_rows())
    missing, none, text = _rows(), _rows(), _rows()
    del missing[2]["note"]
    none[2]["note"] = None
    text[2]["count"] = "2"
    assert len({base["digest32"], _compact(missing)["digest32"], _compact(none)["digest32"], _compact(text)["digest32"]}) == 4
    assert _changed_fields(base, _compact(missing)) == {"note"}
    assert _changed_fields(base, _compact(text)) == {"count"}


def test_list_of_non_dicts_has_no_field_digests() -> None:
    compacted = _compact([float(index) for index in range(LARGE_LIST_LIMIT + 1)])  # type: ignore[arg-type]
    assert "field_digests" not in compacted and compacted["list_length"] == LARGE_LIST_LIMIT + 1


@pytest.mark.parametrize("length", [LARGE_LIST_LIMIT])
def test_short_lists_are_not_compacted(length: int) -> None:
    assert compact_large_lists([{"a": 1.0}] * length) == [{"a": 1.0}] * length
