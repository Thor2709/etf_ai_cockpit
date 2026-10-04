"""Paper-trading, canary, incident and TCA read models for presentation (application; ADR-0002)."""

from pathlib import Path

from etf_cockpit.core.paths import ROOT


def load_paper_trade_rows(root: Path) -> tuple[dict[str, object], ...]:
    """Return safe, local paper-trade rows for presentation selectors."""

    from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError

    try:
        return PaperLedger(root).trade_rows()
    except (OSError, PaperLedgerError, ValueError):
        return ()


def load_canary_status(
    root: Path | None = None,
    *,
    account_id: str = "local-paper",
    config: object | None = None,
) -> dict[str, object]:
    """Expose the local paper-canary state and its permanently blocked live gate."""

    from etf_cockpit.trading.canary import CanaryConfig, CanaryController, CanaryError

    if config is not None and not isinstance(config, CanaryConfig):
        return {
            "state": "invalid",
            "stage": "disabled",
            "opted_in": False,
            "live_submission": "blocked",
            "live_unmet_dependencies": ["canary_config_invalid"],
            "execution_allowed": False,
        }
    try:
        return CanaryController(root or ROOT, account_id=account_id, config=config).status()
    except (CanaryError, OSError, TypeError, ValueError):
        return {
            "state": "invalid",
            "stage": "disabled",
            "opted_in": False,
            "live_submission": "blocked",
            "live_unmet_dependencies": ["canary_state_unavailable"],
            "execution_allowed": False,
        }


def load_paper_incidents(root: Path, *, account_id: str = "local-paper") -> dict[str, object]:
    """Expose the verified local incident journal to presentation selectors."""

    from etf_cockpit.trading.incidents import IncidentJournal, IncidentJournalError

    journal = IncidentJournal(root, account_id=account_id)
    try:
        projection = journal.snapshot()
        events = projection["events"]
        frozen = bool(projection["frozen"])
    except (OSError, IncidentJournalError, ValueError):
        return {
            "status": "invalid",
            "incidents": [],
            "postmortems": [],
            "reconciliations": [],
            "frozen": True,
            "reason_code": "incident_journal_invalid",
            "execution_allowed": False,
        }
    return {
        "status": "frozen" if frozen else "available",
        "incidents": [dict(event["payload"]) for event in events if event["event_type"] == "incident_recorded"],
        "postmortems": [dict(event["payload"]) for event in events if event["event_type"] == "postmortem_recorded"],
        "reconciliations": [dict(event["payload"]) for event in events if event["event_type"] == "reconciliation_recorded"],
        "frozen": frozen,
        "source_authority": "local_paper_incident_journal",
        "execution_allowed": False,
    }


def load_paper_timeline(
    root: Path,
    instrument_id: str,
    *,
    account_id: str = "local-paper",
) -> dict[str, object]:
    """Read one paper account's validated lifecycle history for presentation."""

    from etf_cockpit.portfolio.paper_trading import (
        PaperLedger,
        PaperLedgerError,
        PaperLedgerIntegrityError,
    )

    ledger = PaperLedger(root, account_id=account_id)
    if not ledger.path.exists():
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "rows": [],
            "reason_code": "paper_ledger_missing",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    try:
        rows = ledger.timeline_rows(instrument_id)
    except (OSError, PaperLedgerIntegrityError, PaperLedgerError, ValueError):
        return {
            "status": "invalid",
            "instrument_id": str(instrument_id),
            "rows": [],
            "reason_code": "paper_ledger_invalid",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    return {
        "status": "available",
        "instrument_id": str(instrument_id),
        "rows": list(rows),
        "source_authority": "local_paper_ledger",
        "message": "Recorded paper lifecycle history; this is not a historical account reconstruction.",
        "execution_allowed": False,
    }


def load_paper_tca_view(storage_root: Path | None = None, *, account_id: str = "local-paper") -> dict[str, object]:
    """Load ledger-backed fill attribution and persist completed-fill projections."""

    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError
    from etf_cockpit.trading.tca import (
        TCAAttributionStore,
        TCACalculator,
        calibrate_completed_fills,
    )

    root = Path(storage_root or ROOT).resolve()
    ledger = PaperLedger(root, account_id=account_id)
    if not ledger.path.exists():
        return {
            "status": "unavailable",
            "rows": [],
            "calibration": calibrate_completed_fills(()),
            "reason_code": "paper_ledger_missing",
            "message": "Paper ledger is missing; no fills or costs are inferred.",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    try:
        orders = {str(row.get("order_id")): row for row in ledger.orders()}
        fills = ledger.trade_rows()
        calculator = TCACalculator()
        cumulative_fills: dict[str, float] = {}
        records_list = []
        for fill in fills:
            order_id = str(fill.get("order_id"))
            order = orders.get(order_id)
            cumulative = cumulative_fills.get(order_id, 0.0) + float(fill.get("quantity", 0.0))
            cumulative_fills[order_id] = cumulative
            order_quantity = float((order or {}).get("quantity", 0.0))
            fill_is_completion = (
                order is not None
                and order.get("status") == "filled"
                and order_quantity > 0
                and cumulative + 1e-8 >= order_quantity
            )
            records_list.append(
                calculator.calculate(
                    fill,
                    order,
                    fill_is_completion=fill_is_completion,
                    account_id=account_id,
                )
            )
        records = tuple(records_list)
        store = TCAAttributionStore(ledger.path.parent / "tca_attributions")
        store.persist(records)
        stored_records = store.load()
    except (OSError, PaperLedgerError, ValueError, TypeError):
        return {
            "status": "invalid",
            "rows": [],
            "calibration": calibrate_completed_fills(()),
            "reason_code": "paper_tca_unavailable",
            "message": "Paper ledger or persisted TCA attribution is invalid; no costs are reported.",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    limitations = tuple(
        sorted({item for record in records for item in record.benchmark_limitations})
    )
    completed = sum(record.completed_order for record in records)
    return {
        "status": "available",
        "rows": [record.as_dict() for record in records],
        "calibration": calibrate_completed_fills(records),
        "coverage": {
            "fill_count": len(records),
            "order_linked_fill_count": sum(record.association_status == "order_linked" for record in records),
            "unexpected_fill_count": sum(record.association_status == "unexpected" for record in records),
            "completed_fill_count": completed,
            "decomposed_fill_count": sum(record.reconciliation_status == "reconciled" for record in records),
            "persisted_attribution_count": len(stored_records),
            "benchmark_limitations": list(limitations),
        },
        "reason_code": None if records else "no_fills_recorded",
        "message": (
            "Fill fees reconcile to the paper ledger. Delay, spread and impact require decision and arrival benchmarks; "
            "missing benchmarks remain unavailable."
        ),
        "source_authority": "local_paper_ledger",
        "execution_allowed": False,
    }
