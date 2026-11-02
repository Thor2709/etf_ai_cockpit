"""Read-only projection of the local paper incident freeze state.

Open defaults: status reads the configured ``local-paper`` incident journal and
returns at most 25 active incidents. The read never acquires the journal lock or
repairs a missing/interrupted head anchor; inconsistent state stays unavailable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_incident_status(root: Path, *, account_id: str = "local-paper") -> dict[str, Any]:
    """Read a verified incident freeze projection without locking or writing files."""

    from etf_cockpit.trading.incidents import IncidentJournal, IncidentJournalError

    journal = IncidentJournal(Path(root).resolve(), account_id=account_id)

    def refuse_repair(_events: list[dict[str, object]]) -> None:
        raise IncidentJournalError("incident projection needs a journal repair")

    # _read_events is the canonical hash-chain verifier and has no lock itself. Its
    # recovery branch can write an anchor, so replace that branch for this reader.
    journal._roll_forward_anchor = refuse_repair  # type: ignore[method-assign]
    try:
        events = journal._read_events()
    except (OSError, IncidentJournalError, ValueError) as exc:
        return {
            "status": "unavailable",
            "frozen": None,
            "active_incidents": None,
            "reason": f"incident projection unavailable without a journal lock ({type(exc).__name__})",
            "execution_allowed": False,
        }

    active = journal._active_incidents(events)
    return {
        "status": "frozen" if active else "available",
        "account_id": account_id,
        "frozen": bool(active),
        "active_incidents": active[:25],
        "truncated": len(active) > 25,
        "source_authority": "local_paper_incident_journal",
        "execution_allowed": False,
    }


__all__ = ["load_incident_status"]
