"""Frozen wall clock for the capture subprocess.

Installed BEFORE any ``etf_cockpit`` import: modules do ``from datetime import date, datetime``, so replacing
the two classes on the ``datetime`` module freezes every later ``date.today()`` / ``datetime.now()`` /
``datetime.utcnow()`` read.  ``time.time`` is only COUNTED (it also drives lock timeouts and file mtimes, where a
frozen value could hang the run); no pinned value depends on it.  ``pandas.Timestamp.now`` is a compiled
classmethod and cannot be replaced; its two call sites on the pinned paths only feed volatile fields
(``ingested_at``) that no fixture records.  Each read is recorded (caller module, kind) so a test can prove which
clock reads happened.

Two independent instants are used so wall-clock independence can be proven:

* ``today``   - the pinned business date; sample prices end here and staleness is measured against it.
* ``now``     - the pinned instant behind timestamps; shifted by ``now_offset_days`` in the sanity check.  No
  golden value may depend on it (volatile fields are excluded from every fixture).
"""

from __future__ import annotations

import datetime as _datetime
import sys
import time as _time
from collections import Counter

PINNED_TODAY = _datetime.date(2026, 9, 30)
PINNED_NOW = _datetime.datetime(2026, 9, 30, 12, 0, 0, tzinfo=_datetime.timezone.utc)

_REAL_DATE = _datetime.date
_REAL_DATETIME = _datetime.datetime
READS: Counter[str] = Counter()


def _caller() -> str:
    frame = sys._getframe(2)
    return str(frame.f_globals.get("__name__", "?"))


class _DateMeta(type):
    def __instancecheck__(cls, instance: object) -> bool:
        return isinstance(instance, _REAL_DATE)

    def __subclasscheck__(cls, subclass: type) -> bool:
        return issubclass(subclass, _REAL_DATE)


class _DatetimeMeta(type):
    def __instancecheck__(cls, instance: object) -> bool:
        return isinstance(instance, _REAL_DATETIME)

    def __subclasscheck__(cls, subclass: type) -> bool:
        return issubclass(subclass, _REAL_DATETIME)


def install(*, today: _datetime.date = PINNED_TODAY, now: _datetime.datetime = PINNED_NOW) -> None:
    """Freeze ``date.today`` and ``datetime.now/utcnow/today``; count ``time.time`` reads."""

    class FrozenDate(_REAL_DATE, metaclass=_DateMeta):
        @classmethod
        def today(cls) -> _REAL_DATE:
            READS[f"{_caller()}:date.today"] += 1
            return today

    class FrozenDatetime(_REAL_DATETIME, metaclass=_DatetimeMeta):
        @classmethod
        def now(cls, tz: _datetime.tzinfo | None = None) -> _REAL_DATETIME:
            READS[f"{_caller()}:datetime.now"] += 1
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

        @classmethod
        def utcnow(cls) -> _REAL_DATETIME:
            READS[f"{_caller()}:datetime.utcnow"] += 1
            return now.replace(tzinfo=None)

        @classmethod
        def today(cls) -> _REAL_DATETIME:
            READS[f"{_caller()}:datetime.today"] += 1
            return now.replace(tzinfo=None)

    real_time = _time.time

    def counted_time() -> float:
        READS[f"{_caller()}:time.time"] += 1
        return real_time()

    _datetime.date = FrozenDate  # type: ignore[misc]
    _datetime.datetime = FrozenDatetime  # type: ignore[misc]
    _time.time = counted_time  # type: ignore[assignment]
