"""Canonical service for a price-bound, gate-checked manual paper proposal.

Defaults: prices come from the validated daily price book and must include a
per-row ``known_at`` no later than the current UTC time. Manual orders do not
carry an AI-supplied price, expected benefit, quote, fee or FX rate. Missing
price, currency, FX, benefit, authority or account evidence stays unavailable
and blocks proposal acceptance. Optimiser, confidence and concentration evidence
is resolved only from policy-validated stored proposals with matching quantity,
ledger and price revisions. Friction uses the local canonical paper execution
configuration; its benefit/uncertainty assumptions are never AI inputs.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Mapping
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.config import load_config
from etf_cockpit.core.event_policy import EventBlockPolicy
from etf_cockpit.data.fx_data import build_fx_rate_snapshot, fx_cross_rate, load_fx_rates
from etf_cockpit.portfolio.costs import average_daily_value_eur, estimate_execution_cost
from etf_cockpit.portfolio.paper_bots_execution import PriceBook, load_execution_config
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError, load_proposal_for_paper
from etf_cockpit.portfolio.proposal_policy import (
    REQUIRED_GATES,
    GateEvidence,
    ProposalRequest,
    build_proposal_decision,
    current_authority_policy_checksum,
    save_proposal_decision,
    load_proposal_records,
)
from etf_cockpit.signals.friction_edge import evaluate_friction_gate


def _unavailable(reason: str, *, instrument_id: str, account_id: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "instrument_id": instrument_id,
        "account_id": account_id,
        "price": None,
        "fee": None,
        "fx_rate": None,
        "proposal": None,
        "block_reasons": [reason],
        "unavailable_reason": reason,
        "execution_allowed": False,
    }


def _instrument_currency(snapshot: object, instrument_id: str) -> str | None:
    config = getattr(snapshot, "config", None)
    universe = getattr(config, "universe", None)
    by_id = getattr(universe, "by_id", None)
    if callable(by_id):
        item = by_id().get(instrument_id)
        value = getattr(item, "currency", None) if item is not None else None
        if isinstance(value, str) and len(value.strip()) == 3:
            return value.strip().upper()
    return None


def _point_in_time_fx(root: Path, base: str, quote: str, cutoff: datetime) -> float | None:
    if base == quote:
        return 1.0
    frame = load_fx_rates(root / "data" / "clean" / "fx.parquet")
    snapshot = build_fx_rate_snapshot(frame, decision_time=cutoff, known_at=cutoff)
    cross = fx_cross_rate(snapshot, base, quote)
    return float(cross.rate) if cross is not None and snapshot.available else None


def _evaluate_manual_pretrade(
    root: Path,
    account_id: str,
    proposal: Mapping[str, object],
    *,
    execution_price: float,
    quantity_delta: float,
    fx_rate: float,
    occurred_at: datetime,
) -> dict[str, object]:
    """Run the canonical independent paper controls against the latest ledger state."""

    try:
        ledger = PaperLedger(Path(root), account_id=account_id)
        snapshot = ledger.snapshot()
        if snapshot.status != "ready":
            return {"status": "unavailable", "allowed": False, "reason": "paper_account_not_ready", "control": "account_state"}
        orders = ledger.orders()
        with ledger._lock, ledger._file_lock():
            paper_events = ledger._read_events()
        from etf_cockpit.trading.pre_trade_controls import PreTradeControls

        result = PreTradeControls(Path(root), account_id=account_id).evaluate_order(
            proposal,
            execution_price=execution_price,
            quantity_delta=quantity_delta,
            fx_rate=fx_rate,
            positions={item.instrument_id.upper(): item.to_payload() for item in snapshot.positions},
            open_orders={str(item.get("order_id", "")): item for item in orders},
            paper_events=paper_events,
            path="paper",
            who="mcp_manual_order",
            occurred_at=occurred_at,
        )
        return {
            "status": "available",
            "allowed": result.allowed,
            "control": result.control,
            "reason": result.reason,
            "order_value": None if result.order_value is None else str(result.order_value),
            "position_exposure": None if result.position_exposure is None else str(result.position_exposure),
            "daily_turnover": None if result.daily_turnover is None else str(result.daily_turnover),
            "execution_allowed": False,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {
            "status": "unavailable",
            "allowed": False,
            "control": "pre_trade_state",
            "reason": f"pre_trade_controls_unavailable:{type(exc).__name__}",
            "execution_allowed": False,
        }


def _stored_manual_evidence(
    root: Path, *, instrument_id: str, held: float, target: float,
    portfolio_revision: str, data_revision: str, cutoff: datetime,
    evidence_refs: tuple[str, ...],
) -> Mapping[str, object] | None:
    """Resolve policy-validated evidence for exactly this ledger, price and trade.

    Proposal references select canonical IDs; research references are journal links,
    never caller-supplied gate values.
    Without references, search the same canonical store. Expired, future-known,
    failed, differently sized or differently bound evidence cannot authorize a trade.
    """
    records = load_proposal_records(directory=root / "data" / "operations" / "proposals")
    proposal_refs = {ref for ref in evidence_refs if ref.startswith("proposal_")}
    for record in sorted(records, key=lambda item: str(item.get("as_of", "")), reverse=True):
        if proposal_refs and record.get("proposal_id") not in proposal_refs:
            continue
        material = record.get("input_material", {})
        try:
            created = datetime.fromisoformat(str(record["as_of"]))
            expires = datetime.fromisoformat(str(record["expires_at"]))
            gates = {item["gate_id"]: item for item in record["gates"]}
            if (
                record.get("instrument_id") == instrument_id
                and record.get("execution_allowed") is False
                and created <= cutoff < expires
                and material.get("current_quantity") == held
                and material.get("target_quantity") == target
                and material.get("portfolio_revision") == portfolio_revision
                and material.get("data_revision") == data_revision
                and material.get("optimiser_output_id")
                and all(gates.get(name, {}).get("passed") is True for name in
                        ("optimizer_output", "model_confidence", "concentration"))
            ):
                return record
        except (KeyError, TypeError, ValueError):
            continue
    return None


def preview_manual_paper_order(
    *,
    root: Path,
    snapshot: object,
    account_id: str,
    instrument_id: str,
    side: str,
    quantity: float | None = None,
    amount_eur: float | None = None,
    target_weight: float | None = None,
    rationale: str,
    evidence_refs: tuple[str, ...] = (),
    as_of: datetime | None = None,
    persist: bool = False,
) -> dict[str, object]:
    """Project a manual paper proposal using the saved, point-in-time price book."""

    root = Path(root).resolve()
    instrument = str(instrument_id).strip().upper()
    account = str(account_id).strip()
    order_side = str(side).strip().lower()
    cutoff = as_of or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        return _unavailable("as_of_must_be_timezone_aware", instrument_id=instrument, account_id=account)
    cutoff = cutoff.astimezone(timezone.utc)
    if order_side not in {"buy", "sell"}:
        return _unavailable("side_must_be_buy_or_sell", instrument_id=instrument, account_id=account)
    selected = sum(value is not None for value in (quantity, amount_eur, target_weight))
    if selected != 1:
        return _unavailable("supply_exactly_one_of_quantity_amount_eur_or_target_weight", instrument_id=instrument, account_id=account)
    try:
        ledger = PaperLedger(root, account_id=account)
        account_state = ledger.snapshot()
    except (OSError, PaperLedgerError, ValueError) as exc:
        return _unavailable(f"paper_account_unavailable:{type(exc).__name__}", instrument_id=instrument, account_id=account)
    if account_state.status != "ready":
        return _unavailable("paper_account_not_ready", instrument_id=instrument, account_id=account)

    book = PriceBook.from_root(root)
    bar = book.last_bar(instrument, cutoff.date(), known_by=cutoff)
    if bar is None:
        return _unavailable(book.error or "committed_price_unavailable_at_cutoff", instrument_id=instrument, account_id=account)
    price_value = bar.get("close")
    known_at = bar.get("_known_at")
    if isinstance(price_value, bool) or not isinstance(price_value, (int, float)) or not pd.notna(price_value) or float(price_value) <= 0:
        return _unavailable("committed_close_unavailable", instrument_id=instrument, account_id=account)
    if not isinstance(known_at, datetime) or known_at.tzinfo is None or known_at > cutoff:
        return _unavailable("committed_close_known_at_unavailable", instrument_id=instrument, account_id=account)

    quote_currency = _instrument_currency(snapshot, instrument)
    account_currency = str(account_state.base_currency or "").strip().upper()
    if quote_currency is None or len(account_currency) != 3:
        return _unavailable("quote_or_account_currency_unavailable", instrument_id=instrument, account_id=account)
    try:
        fx_rate = _point_in_time_fx(root, quote_currency, account_currency, cutoff)
        eur_rate = _point_in_time_fx(root, quote_currency, "EUR", cutoff)
    except (OSError, TypeError, ValueError, KeyError):
        fx_rate, eur_rate = None, None
    if fx_rate is None or not pd.notna(fx_rate) or fx_rate <= 0 or eur_rate is None or not pd.notna(eur_rate) or eur_rate <= 0:
        return _unavailable("point_in_time_fx_unavailable", instrument_id=instrument, account_id=account)

    held = next((float(item.quantity) for item in account_state.positions if item.instrument_id.upper() == instrument), 0.0)
    if amount_eur is not None:
        amount = float(amount_eur)
        if not pd.notna(amount) or amount <= 0:
            return _unavailable("amount_eur_must_be_positive", instrument_id=instrument, account_id=account)
        resolved_quantity = amount / (float(price_value) * eur_rate)
    elif target_weight is not None:
        weight = float(target_weight)
        if not pd.notna(weight) or not 0.0 <= weight <= 1.0:
            return _unavailable("target_weight_must_be_between_zero_and_one", instrument_id=instrument, account_id=account)
        if account_state.equity is None or not pd.notna(account_state.equity) or account_state.equity <= 0:
            return _unavailable("account_equity_unavailable_for_target_weight", instrument_id=instrument, account_id=account)
        desired = (float(account_state.equity) * weight) / (float(price_value) * fx_rate)
        delta = desired - held
        resolved_quantity = delta if order_side == "buy" else -delta
    else:
        resolved_quantity = float(quantity)
    if not pd.notna(resolved_quantity) or resolved_quantity <= 0:
        return _unavailable("order_quantity_unavailable_or_non_positive", instrument_id=instrument, account_id=account)
    signed_delta = resolved_quantity if order_side == "buy" else -resolved_quantity
    if signed_delta < 0 and resolved_quantity > held + 1e-8:
        return _unavailable("paper_sell_exceeds_available_position", instrument_id=instrument, account_id=account)

    order_value_eur = resolved_quantity * float(price_value) * eur_rate
    try:
        history = pd.DataFrame([
            book.bar(instrument, day, known_by=cutoff) or {}
            for day in book._dates.get(instrument, []) if day <= cutoff.date()
        ])
        adv_eur = average_daily_value_eur(
            history.get("volume", pd.Series(dtype=float)), history.get("close", pd.Series(dtype=float)),
            currency=quote_currency, fx_to_eur=eur_rate,
        )
        cost = estimate_execution_cost(load_config(), instrument, order_value_eur, adv_eur=adv_eur)
        _, execution_config = load_execution_config(root / "configs" / "paper_bots_execution_v1.yaml")
        friction = evaluate_friction_gate(
            execution_config.get("rule_expected_benefit_bps"),
            order_value_eur=order_value_eur,
            cost_estimate=cost.as_dict(),
            uncertainty_bps=execution_config.get("rule_uncertainty_bps"),
        )
        fee = float(cost.commission_eur) / eur_rate
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return _unavailable(f"order_cost_unavailable:{type(exc).__name__}", instrument_id=instrument, account_id=account)

    price_fingerprint = pd.util.hash_pandas_object(pd.Series([instrument, str(bar.get("date")), str(known_at), float(price_value)]), index=False).astype("uint64").to_list()
    data_revision = "price:" + ":".join(str(item) for item in price_fingerprint)
    source = _stored_manual_evidence(
        root, instrument_id=instrument, held=held, target=held + signed_delta,
        portfolio_revision=str(account_state.ledger_hash or ""), data_revision=data_revision,
        cutoff=cutoff, evidence_refs=evidence_refs,
    )
    if source is None:
        result = _unavailable("matching_canonical_proposal_evidence_unavailable_or_failing", instrument_id=instrument, account_id=account)
        result["gates"] = [GateEvidence(name, False, "Matching canonical evidence is unavailable or failing.").to_payload()
                           for name in ("optimizer_output", "model_confidence", "concentration")]
        return result
    material = source["input_material"]
    if any(material.get(field) != execution_config.get(config_field) for field, config_field in
           (("strategy_id", "strategy_id"), ("model_id", "model_id"), ("account_id", "account_capability"))):
        return _unavailable("canonical_rule_authority_binding_mismatch", instrument_id=instrument, account_id=account)
    source_gates = {item["gate_id"]: GateEvidence(**item) for item in source["gates"]}
    gates_by_id = {
        "optimizer_output": source_gates["optimizer_output"],
        "portfolio_state": GateEvidence("portfolio_state", True, "The local paper account ledger is open and reconciled."),
        "data_freshness": GateEvidence("data_freshness", known_at <= cutoff, "Committed close and known_at are bound to the current cutoff." if known_at <= cutoff else "The committed close is newer than the cutoff."),
        "model_confidence": source_gates["model_confidence"],
        "liquidity": GateEvidence("liquidity", bool(getattr(cost, "capacity_eur", None) is not None and order_value_eur <= float(cost.capacity_eur)), "Order-size capacity is evaluated by the canonical cost model."),
        "cost": GateEvidence("cost", friction.status == "pass" and friction.propose is True, friction.reason),
        "concentration": source_gates["concentration"],
        "account_authority": GateEvidence("account_authority", True, "The request is bound to an open local paper account."),
    }
    try:
        event_policy = material.get("event_control", {}).get("policy")
        inherited_gates = tuple(gate for name, gate in source_gates.items()
                                if name not in {*REQUIRED_GATES, "event_risk", "friction_edge", "pre_trade"})
        request = ProposalRequest(
                instrument_id=instrument,
                current_quantity=held,
                target_quantity=held + signed_delta,
                strategy_id=material["strategy_id"],
                strategy_stage=material["strategy_stage"],
                model_id=material["model_id"],
                model_stage=material["model_stage"],
                account_id=material["account_id"],
                account_stage=material["account_stage"],
                optimiser_output_id=str(material["optimiser_output_id"]),
                portfolio_revision=str(account_state.ledger_hash or ""),
                data_revision=data_revision,
                as_of=cutoff,
                expires_at=min(cutoff + timedelta(minutes=15), datetime.fromisoformat(str(source["expires_at"]))),
                authority_policy_checksum=current_authority_policy_checksum(),
                gate_evidence=(*tuple(gates_by_id[name] for name in REQUIRED_GATES), *inherited_gates),
                rationale=rationale.strip(),
                friction_gate=friction,
                approvals=tuple(material.get("supplied_approvals", ())),
                event_calendar_path=root / "data" / "clean" / "event_calendar.parquet",
                event_policy=EventBlockPolicy.model_validate(event_policy) if event_policy is not None else None,
            )
        decision = build_proposal_decision(request)
        pre_trade = _evaluate_manual_pretrade(
            root,
            account,
            decision.to_payload(),
            execution_price=float(price_value),
            quantity_delta=signed_delta,
            fx_rate=fx_rate,
            occurred_at=cutoff,
        )
        pre_trade_gate = GateEvidence(
            "pre_trade",
            pre_trade.get("status") == "available" and pre_trade.get("allowed") is True,
            str(pre_trade.get("reason", "Pre-trade controls are unavailable.")),
        )
        decision = build_proposal_decision(
            replace(request, gate_evidence=(*request.gate_evidence, pre_trade_gate))
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return _unavailable(f"proposal_policy_unavailable:{type(exc).__name__}", instrument_id=instrument, account_id=account)
    if persist:
        save_proposal_decision(decision, directory=root / "data" / "operations" / "proposals")
    failures = [gate.reason for gate in decision.gates if not gate.passed]
    return {
        "status": "proposal_ready" if decision.proposal_allowed else "blocked",
        "proposal_id": decision.proposal_id,
        "proposal": decision.to_payload(),
        "proposal_allowed": decision.proposal_allowed,
        "instrument_id": instrument,
        "account_id": account,
        "side": order_side,
        "quantity": resolved_quantity,
        "price": float(price_value),
        "price_known_at": known_at,
        "currency": quote_currency,
        "account_currency": account_currency,
        "rationale": rationale.strip(),
        "evidence_refs": list(dict.fromkeys((*evidence_refs, str(source["proposal_id"])))),
        "fee": fee,
        "fx_rate": fx_rate,
        "eur_rate": eur_rate,
        "cost_estimate": cost.as_dict(),
        "friction": friction.__dict__,
        "pre_trade_decision": pre_trade,
        "gates": [item.to_payload() for item in decision.gates],
        "block_reasons": failures,
        "confirm_token": None,
        "execution_allowed": False,
    }


def persist_manual_paper_proposal(preview: Mapping[str, object], *, root: Path) -> dict[str, object]:
    proposal = preview.get("proposal")
    if not isinstance(proposal, Mapping):
        raise ValueError("A complete manual paper preview is required.")
    from etf_cockpit.portfolio.proposal_policy import load_proposal_records

    decision_records = load_proposal_records(directory=Path(root) / "data" / "operations" / "proposals")
    if not any(item.get("proposal_id") == proposal.get("proposal_id") for item in decision_records):
        raise ValueError("The proposal has not been persisted by the canonical proposal service.")
    terms = {
        "proposal_id": str(proposal.get("proposal_id", "")),
        "account_id": str(preview.get("account_id", "")),
        "instrument_id": str(preview.get("instrument_id", "")),
        "side": str(preview.get("side", "")),
        "rationale": str(preview.get("rationale", "")),
        "evidence_refs": list(preview.get("evidence_refs", ())),
        "quantity": preview.get("quantity"),
        "execution_price": preview.get("price"),
        "fee": preview.get("fee"),
        "fx_rate": preview.get("fx_rate"),
        "eur_rate": preview.get("eur_rate"),
        "price_known_at": preview.get("price_known_at"),
        "currency": preview.get("currency"),
        "account_currency": preview.get("account_currency"),
        "execution_allowed": False,
    }
    terms["checksum"] = hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    destination = Path(root) / "data" / "operations" / "paper_order_terms" / f"{terms['proposal_id']}.json"
    payload = (json.dumps(terms, sort_keys=True, indent=2, default=str, allow_nan=False) + "\n").encode("utf-8")
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing != terms:
            raise ValueError("Saved paper order terms conflict with the proposal.")
    else:
        atomic_write_bytes(destination, payload, lambda candidate: json.loads(candidate.read_text(encoding="utf-8")))
    return dict(preview)


def accept_manual_paper_proposal(
    *, root: Path, proposal_id: str, instrument_id: str, quantity: float,
) -> dict[str, object]:
    """Accept only a gate-approved proposal through the canonical paper ledger."""

    proposal = load_proposal_for_paper(root, proposal_id)
    if str(proposal.get("instrument_id", "")).upper() != instrument_id.upper():
        raise ValueError("instrument_id does not match the saved proposal")
    delta = proposal.get("quantity_delta")
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or abs(float(delta)) != float(quantity):
        raise ValueError("quantity does not match the saved proposal")
    if proposal.get("proposal_allowed") is not True:
        raise PaperLedgerError("Only a gate-approved manual paper proposal can be accepted.")
    terms_path = Path(root) / "data" / "operations" / "paper_order_terms" / f"{proposal_id}.json"
    try:
        terms = json.loads(terms_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperLedgerError("Server-derived paper order terms are unavailable.") from exc
    checksum = terms.pop("checksum", None)
    expected = hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    if checksum != expected or terms.get("proposal_id") != proposal_id or terms.get("execution_allowed") is not False:
        raise PaperLedgerError("Server-derived paper order terms failed integrity validation.")
    if str(terms.get("instrument_id", "")).upper() != instrument_id.upper() or float(terms.get("quantity")) != float(quantity):
        raise PaperLedgerError("Order inputs do not match the server-derived paper terms.")
    try:
        known_at = datetime.fromisoformat(str(terms["price_known_at"]).replace("Z", "+00:00"))
        price_book = PriceBook.from_root(Path(root))
        current_bar = price_book.last_bar(instrument_id, datetime.now(timezone.utc).date(), known_by=datetime.now(timezone.utc))
    except (KeyError, TypeError, ValueError) as exc:
        raise PaperLedgerError("The committed price could not be revalidated.") from exc
    if current_bar is None or current_bar.get("_known_at") != known_at or float(current_bar.get("close", 0.0)) != float(terms.get("execution_price")):
        raise PaperLedgerError("The committed close changed after preview; create a fresh proposal.")
    now = datetime.now(timezone.utc)
    quote_currency = str(terms.get("currency", "")).upper()
    account_currency = str(terms.get("account_currency", "")).upper()
    try:
        current_fx = _point_in_time_fx(Path(root), quote_currency, account_currency, now)
        current_eur_rate = _point_in_time_fx(Path(root), quote_currency, "EUR", now)
    except (OSError, TypeError, ValueError, KeyError):
        current_fx, current_eur_rate = None, None
    if current_fx is None or current_eur_rate is None or float(current_fx) != float(terms.get("fx_rate")) or float(current_eur_rate) != float(terms.get("eur_rate")):
        raise PaperLedgerError("The point-in-time FX rate changed or became unavailable; create a fresh proposal.")
    try:
        current_cost = estimate_execution_cost(load_config(), instrument_id, float(terms["quantity"]) * float(terms["execution_price"]) * float(current_eur_rate))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise PaperLedgerError("The current paper order cost is unavailable.") from exc
    if float(current_cost.commission_eur) / float(current_eur_rate) != float(terms.get("fee")):
        raise PaperLedgerError("The paper order fee changed after preview; create a fresh proposal.")
    pre_trade = _evaluate_manual_pretrade(
        Path(root),
        str(terms["account_id"]),
        proposal,
        execution_price=float(terms["execution_price"]),
        quantity_delta=float(delta),
        fx_rate=float(terms["fx_rate"]),
        occurred_at=now,
    )
    if pre_trade.get("status") != "available" or pre_trade.get("allowed") is not True:
        raise PaperLedgerError(str(pre_trade.get("reason", "Independent pre-trade controls blocked the order.")))

    from etf_cockpit.application.api import LocalApplicationApi
    from etf_cockpit.application.contracts import PageRequest, PaperFillRequest, PaperProposalAcceptRequest
    from etf_cockpit.data.decision_journal import DecisionJournal, JournalEntry

    account_id = str(terms["account_id"])
    api = LocalApplicationApi(lambda: None, root=Path(root))
    existing_order = None
    offset = 0
    while existing_order is None:
        page = api.get_paper_orders(
            PageRequest(offset=offset, limit=500),
            account_id=account_id,
        )
        existing_order = next((item for item in page.items if item.proposal_id == proposal_id), None)
        if existing_order is not None or page.next_offset is None:
            break
        offset = page.next_offset
    if existing_order is None:
        state = PaperLedger(Path(root), account_id=account_id).snapshot()
        if state.ledger_hash != proposal.get("input_material", {}).get("portfolio_revision"):
            raise PaperLedgerError("The paper account changed after preview; create a fresh proposal.")
        revalidated = preview_manual_paper_order(
            root=Path(root), snapshot=SimpleNamespace(config=load_config()), account_id=account_id, instrument_id=instrument_id,
            side=str(terms["side"]), quantity=float(quantity),
            rationale=str(terms["rationale"]), evidence_refs=tuple(terms.get("evidence_refs", ())),
        )
        if revalidated.get("status") != "proposal_ready":
            raise PaperLedgerError("Current canonical evidence or gates no longer permit this paper order.")
        accepted = api.accept_paper_proposal(
            PaperProposalAcceptRequest(
                account_id=account_id,
                proposal_id=proposal_id,
                execution_price=float(terms["execution_price"]),
                fee=float(terms.get("fee", 0.0)),
                fx_rate=None if terms.get("fx_rate") is None else float(terms["fx_rate"]),
                mode="manual_accept",
            )
        )
        order_id = accepted.order_id
    else:
        if (
            existing_order.instrument_id.upper() != instrument_id.upper()
            or existing_order.quantity != float(quantity)
            or existing_order.execution_price != float(terms["execution_price"])
            or existing_order.account_id != account_id
        ):
            raise PaperLedgerError("An existing order conflicts with the saved paper proposal terms.")
        order_id = existing_order.order_id
    fill_id = "mcp_fill_" + hashlib.sha256(f"{proposal_id}:{order_id}".encode("utf-8")).hexdigest()[:24]
    order = api.fill_paper_order(
        PaperFillRequest(
            account_id=account_id,
            order_id=order_id,
            fill_id=fill_id,
            quantity=float(quantity),
            price=float(terms["execution_price"]),
            fx_rate=None if terms.get("fx_rate") is None else float(terms["fx_rate"]),
        )
    )
    journal = DecisionJournal()
    entry_id = "paper_order_" + order.order_id
    prior = next((item for item in journal.list_entries(root=Path(root)) if item.journal_entry_id == entry_id), None)
    if prior is not None:
        if proposal_id not in prior.proposal_ids or order.order_id not in prior.order_ids:
            raise PaperLedgerError("The paper order journal identity conflicts with the saved order.")
        entry = prior
    else:
        entry = journal.create(
            JournalEntry(
                journal_entry_id=entry_id,
                created_at=datetime.now(timezone.utc).isoformat(),
                thesis=str(terms.get("rationale", "")) or "Manual paper proposal",
                decision="Accepted paper proposal for simulation.",
                outcome="pending",
                evidence_refs=list(terms.get("evidence_refs", ())),
                instrument_ids=[instrument_id.upper()],
                proposal_ids=[proposal_id],
                order_ids=[order.order_id],
                portfolio_context={"account_id": account_id, "execution_allowed": False},
            ),
            root=Path(root),
        )
    return {
        "order": order.model_dump(mode="python"),
        "fill": {
            "fill_id": fill_id,
            "quantity": float(quantity),
            "price": float(terms["execution_price"]),
            "fee": float(terms.get("fee", 0.0)),
            "fx_rate": terms.get("fx_rate"),
            "execution_allowed": False,
        },
        "journal_entry_id": entry.journal_entry_id,
        "pre_trade_decision": pre_trade,
    }


def find_paper_order_account(root: Path, order_id: str) -> str | None:
    """Resolve one saved order to its local account through the canonical ledger."""

    accounts = ["local-paper"]
    account_root = Path(root) / "data" / "operations" / "paper" / "accounts"
    if account_root.is_dir() and not account_root.is_symlink():
        accounts.extend(path.name for path in account_root.iterdir() if path.is_dir() and not path.is_symlink())
    for account_id in accounts:
        try:
            if any(str(row.get("order_id")) == order_id for row in PaperLedger(root, account_id=account_id).orders()):
                return account_id
        except (OSError, PaperLedgerError, ValueError):
            continue
    return None


def activate_paper_kill_switch(root: Path, reason: str) -> tuple[dict[str, str], ...]:
    """Activate controls for every manual and forward-bot paper account."""

    from etf_cockpit.trading.pre_trade_controls import PreTradeControls

    root = Path(root)
    activated: list[dict[str, str]] = []
    manual_accounts = ["local-paper"]
    manual_account_root = root / "data" / "operations" / "paper" / "accounts"
    if manual_account_root.is_dir() and not manual_account_root.is_symlink():
        manual_accounts.extend(
            path.name for path in manual_account_root.iterdir() if path.is_dir() and not path.is_symlink()
        )
    for account_id in sorted(set(manual_accounts)):
        ledger = PaperLedger(root, account_id=account_id)
        PreTradeControls(root, account_id=account_id).activate_kill_switch(
            who="mcp", reason=reason, paper_ledger=ledger,
        )
        activated.append({"scope": "manual", "account_id": account_id})

    bot_root = root / "data" / "paper_bots" / "ledger"
    bot_account_root = bot_root / "data" / "operations" / "paper" / "accounts"
    if bot_account_root.is_dir() and not bot_account_root.is_symlink():
        for path in sorted(bot_account_root.iterdir()):
            if not path.is_dir() or path.is_symlink():
                continue
            ledger = PaperLedger(bot_root, account_id=path.name)
            PreTradeControls(bot_root, account_id=path.name).activate_kill_switch(
                who="mcp", reason=reason, paper_ledger=ledger,
            )
            activated.append({"scope": "forward_bot", "account_id": path.name})
    return tuple(activated)


def load_paper_controls_status(root: Path, account_id: str) -> dict[str, object]:
    """Read the canonical kill switch, incident, canary and limit projections."""

    from etf_cockpit.application.paper_views import load_canary_status, load_paper_incidents
    from etf_cockpit.trading.pre_trade_controls import PreTradeControlError, PreTradeControls

    controls = PreTradeControls(root, account_id=account_id)
    try:
        limits = controls.load_limits()
        kill_switch = controls.kill_switch_active()
        status = "available"
        limits_data: dict[str, object] | None = {
            "max_order_value": str(limits.max_order_value),
            "max_position_exposure": str(limits.max_position_exposure),
            "max_daily_turnover": str(limits.max_daily_turnover),
            "allowed_instruments": sorted(limits.allowed_instruments),
        }
    except (PreTradeControlError, OSError, ValueError):
        status, kill_switch, limits_data = "unavailable", None, None
    return {
        "status": status,
        "account_id": account_id,
        "kill_switch_active": kill_switch,
        "limits": limits_data,
        "incidents": load_paper_incidents(root, account_id=account_id),
        "canary": load_canary_status(root, account_id=account_id),
        "execution_allowed": False,
    }


__all__ = [
    "accept_manual_paper_proposal", "activate_paper_kill_switch", "find_paper_order_account",
    "load_paper_controls_status", "persist_manual_paper_proposal", "preview_manual_paper_order",
]
