"""Offline seeded-root driver; launched before application imports by test_flows.

Stubs: Yahoo/OpenFIGI identity responses and Yahoo market-data responses use
explicit fixture facts. Issuer/public reference HTTP inputs stay unavailable.
No other application service or persistence path is replaced.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import partial
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pandas as pd


class ToolDefect(Exception):
    pass


def seed(root, flow):
    fixtures = Path(__file__).parent
    code = fixtures.parents[2]
    for name in ("data_readiness_v1.yaml", "paper_bots_execution_v1.yaml", "authority_matrix.yaml",
                 "pre_trade_limits_v1.yaml", "score_engine_v3.yaml", "universe_membership_v1.yaml",
                 "decision_domains_v1.yaml", "costs.yaml", "gate_policy.yaml", "storage_policy.yaml",
                 "portfolio_targets.yaml", "risk_limits.yaml", "settlement_v1.yaml", "data_providers.yaml",
                 "market_calendar_corrections.yaml", "model_settings.yaml"):
        shutil.copyfile(code / "configs" / name, root / "configs" / name)
    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.data.duckdb_store import write_prices
    assert ROOT == root, (ROOT, root)
    metadata = json.loads((fixtures / "flow_root.json").read_text(encoding="utf-8"))
    assert metadata["execution_allowed"] is False
    prices = pd.read_csv(fixtures / "prices.csv")
    assert len(prices) == metadata["data"]["prices"]["rows"]
    write_prices(prices)
    path = root / "data" / "clean" / "prices.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    prices.to_parquet(path)
    # Health and readiness also read the compatibility store; identical fixture evidence.
    # Flow 3 has explicit outside-universe price evidence. Flow 1's newly added
    # instrument has no supplied history and must remain unavailable.
    if flow == 3:
        from etf_cockpit.data.trade_candidate_analysis import write_candidate_price_snapshot
        from etf_cockpit.portfolio.benchmark_reference import adjusted_price_snapshot_binding
        candidate = prices.assign(etf_id="FIXTURE1")
        window = {"start_date": str(candidate["date"].min()), "end_date": "2026-10-30",
                  "decision_time": "2026-10-30T20:00:00Z"}
        binding = adjusted_price_snapshot_binding(candidate, calculation_window=window)
        assert binding is not None
        write_candidate_price_snapshot(candidate, binding)
    directory = root / "data" / "raw" / "trade_candidates"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "yahoo_trade_candidates_l9.csv").write_text(
        "instrument_id,yahoo_symbol,name,asset_type\nFIXTURE1,FIXTURE1,Fixture One,stock\n", encoding="utf-8")
    from etf_cockpit.data.universe_store import import_legacy_universe, save_universe
    universe = import_legacy_universe(root / "configs" / "universe.yaml")
    save_universe(universe.records, "", root=root)
    from etf_cockpit.portfolio.paper_trading import PaperLedger
    PaperLedger(root, account_id="l9-paper").open_account(initial_cash=10000.0)


def identity_get_json(_url):
    return {"quotes": [{"symbol": "FIXTURE1", "longname": "Fixture One", "quoteType": "EQUITY"}]}


def identity_post_json(_url, _payload):
    return [{"data": [{"name": "Fixture One", "ticker": "FIXTURE1", "exchCode": "US"}]}]


def identity_ticker(_symbol):
    return SimpleNamespace(info={"symbol": "FIXTURE1", "longName": "Fixture One", "quoteType": "EQUITY",
                                 "currency": "EUR", "country": "Germany", "exchange": "GER"})


def market_download(symbol, *, start, end, **_kwargs):
    assert symbol == "VWCE.DE", f"No market response fixture for {symbol}"
    prices = pd.read_csv(Path(__file__).parent / "prices.csv")
    dates = pd.to_datetime(prices["date"])
    prices = prices.loc[(dates >= pd.Timestamp(start)) & (dates < pd.Timestamp(end))].copy()
    return prices.rename(columns={"date": "Date", "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "adjusted_close": "Adj Close", "volume": "Volume"}).set_index("Date").rename_axis("Date")


def unavailable_reference_http(*_args, **_kwargs):
    raise OSError("Offline fixture: issuer/public reference input unavailable")


def context(root):
    import yfinance
    from etf_cockpit.application import stock_service
    from etf_cockpit.application.headless_session import HeadlessSession
    from etf_cockpit.application.snapshot_builder import build_snapshot
    from etf_cockpit.data.instrument_lookup import resolve
    from etf_cockpit.data import etf_e1_fetch
    from etf_cockpit.mcp.audit import AuditRecorder
    from etf_cockpit.mcp.confirm import ConfirmationStore
    from etf_cockpit.mcp.registry import CallContext, RateLimiter
    stock_service.lookup_instrument = partial(resolve, get_json=identity_get_json,
        post_json=identity_post_json, ticker_factory=identity_ticker)
    yfinance.download = market_download
    yfinance.Ticker = lambda _symbol: SimpleNamespace(info={}, fast_info={})
    etf_e1_fetch.get_checked = unavailable_reference_http
    session = HeadlessSession(build_snapshot(force_sample=False), root=root)
    assert all(not session.snapshot.model_status.get(name, False) for name in ("timesfm", "timesfm3", "toto"))
    return CallContext(enabled_tiers=frozenset({"read", "edit", "read_job", "research", "paper"}),
        profile="full", client_id="l9-flow", session=session,
        confirmation_store=ConfirmationStore(b"c" * 32), audit=AuditRecorder(sink=lambda _record: None),
        rate_limiter=RateLimiter(path=root / "rate-limits.sqlite3"))


def call(ctx, name, **args):
    from etf_cockpit.mcp.registry import invoke_tool
    from etf_cockpit.mcp.serialise import normalise
    result = invoke_tool(name, args, context=ctx)
    encoded = json.dumps(normalise(result), separators=(",", ":"), allow_nan=False)
    assert len(encoded) <= 8000 * 4, (name, len(encoded))
    def paper_only(value):
        if isinstance(value, dict):
            if "execution_allowed" in value:
                assert value["execution_allowed"] is False
            for item in value.values():
                paper_only(item)
        elif isinstance(value, list):
            for item in value:
                paper_only(item)
    paper_only(normalise(result))
    return result


def state(ctx):
    """Snapshot business persistence plus durable workflows; confirmation/audit excluded."""
    root = ctx.session.root
    paths = [root / "configs" / "universe_store.json"]
    for relative in ("data/operations/proposals", "data/operations/paper_order_terms", "data/paper",
                     "data/ai_research", "data/research"):
        directory = root / relative
        if directory.exists():
            paths.extend(p for p in directory.rglob("*") if p.is_file() and p.suffix != ".lock")
    # Include every business file rather than assume a research/ledger layout.
    for directory in (root / "data", root / "backups"):
        if directory.exists():
            paths.extend(p for p in directory.rglob("*") if p.is_file()
                and p.suffix in {".json", ".jsonl", ".parquet", ".csv"}
                and "logs" not in p.parts)
    files = {str(p.relative_to(root)): p.read_bytes() for p in paths if p.exists()}
    jobs = ctx.session.list_workflows(status=None, offset=0, limit=200)
    return files, jobs


def confirmed(ctx, name, args):
    from etf_cockpit.mcp.errors import ConfirmationError
    before = state(ctx)
    try:
        preview = call(ctx, name, **args)
    except ConfirmationError:
        preview = None
    assert state(ctx) == before, f"{name}: missing token changed persistence/workflows"
    try:
        call(ctx, name, **args, confirm_token="invalid")
    except ConfirmationError:
        pass
    else:
        raise AssertionError(f"{name}: invalid token accepted")
    assert state(ctx) == before, f"{name}: invalid token changed persistence/workflows"
    return preview


def add_instrument(ctx):
    from etf_cockpit.data.universe_store import load_universe
    lookup = call(ctx, "instrument_lookup", identifier="US0378331005")
    assert lookup["resolution"]["isin_status"] == "verified", lookup
    assert not lookup["in_universe"]
    fields = lookup["proposed_fields"]
    args = {"action": "add", "instrument_id": fields["instrument_id"], "fields": fields}
    before = state(ctx)
    staged = call(ctx, "universe_change_preview", **args)
    assert staged["valid"] and state(ctx) == before
    commit_args = {**args, "expected_revision": staged["expected_revision"]}
    confirmed(ctx, "universe_change_commit", commit_args)
    saved = call(ctx, "universe_change_commit", **commit_args, confirm_token=staged["confirm_token"])
    snapshot = load_universe(ctx.session.root)
    assert snapshot.revision == saved["revision"] != staged["expected_revision"]
    assert "FIXTURE1" in {r.instrument_id for r in snapshot.records}
    assert Path(saved["backup_path"]).exists()


def flow1(ctx):
    add_instrument(ctx)
    args = {"source": "prices", "years": 1, "rescore": False}
    preview = confirmed(ctx, "data_refresh", args)
    refresh = call(ctx, "data_refresh", **args, confirm_token=preview["confirm_token"])
    ctx.session.run_next_workflow(workflow_id=refresh["job_id"])
    job = call(ctx, "job_status", job_id=refresh["job_id"])
    assert job["job"].status.value == "succeeded", job
    pipeline = call(ctx, "pipeline_run", steps=["scores"], live_optional_models=False)
    assert pipeline["status"] == "succeeded", pipeline
    assert Path(pipeline["result"]["steps"]["scores"]["output_path"]).is_file()
    job = call(ctx, "job_status", job_id=pipeline["job_id"])
    assert job["job"].status.value == "succeeded"
    explained = call(ctx, "score_explain", instrument_id="FIXTURE1")
    assert explained["score_10"] is None and explained["status"] == "unavailable", explained


def research(ctx, kind="web"):
    item = {"subject": "VWCE", "kind": kind, "claim": "Owner supplied fixture claim", "stance": 0.1,
        "confidence": 0.5, "source_url": "https://example.invalid/l9", "source_title": "L9 fixture",
        "published_at": "2026-10-29T00:00:00Z", "retrieved_at": "2026-10-30T00:00:00Z",
        "excerpt": "Offline fixture evidence; no scoring authority"}
    preview = call(ctx, "research_findings", prepare_items=[item])
    args = {"items": [item], "expected_revision": preview["preview"]["expected_revision"]}
    confirmed(ctx, "research_record_findings", args)
    stored = call(ctx, "research_record_findings", **args, confirm_token=preview["confirm_token"])
    findings = call(ctx, "research_findings", subject="VWCE", kind=kind)
    assert len(stored["ids"]) == 1 and len(findings["findings"]) == 1, findings
    assert stored["scoring_eligible"] is False
    return stored["ids"][0]


def flow2(ctx):
    eligible = call(ctx, "scores_ranked", buy_eligible_only=True, top_n=5)
    assert not eligible["rows"], eligible  # Tiny fixture lacks buy-authorising evidence.
    ranked = call(ctx, "scores_ranked", include_gated=True, top_n=5)
    assert ranked["rows"] and all(not row["buy_eligible"] for row in ranked["rows"])
    for row in ranked["rows"]:
        explained = call(ctx, "score_explain", instrument_id=row["instrument_id"])
        assert explained["score_10"] == row["score_10"]
        call(ctx, "instrument_detail", instrument_id=row["instrument_id"], sections=["overview", "score"])
    call(ctx, "etf_look_through", instrument_id="VWCE", decision_time=datetime(2026, 10, 30, 20, tzinfo=timezone.utc))
    call(ctx, "etf_overlap", instrument_ids=["VWCE"], include_portfolio=True)
    forecasts = call(ctx, "forecast_get", instrument_ids=["VWCE"], horizons=[30])
    assert forecasts["status"] == "unavailable", forecasts
    research(ctx)
    # External findings must not grant buy eligibility or alter app scores.
    assert call(ctx, "scores_ranked", include_gated=True, top_n=5)["rows"] == ranked["rows"]


def flow3(ctx):
    lookup = call(ctx, "instrument_lookup", identifier="US0378331005")
    assert not lookup["in_universe"]
    call(ctx, "score_explain", instrument_id="VWCE")  # Existing-universe branch.
    candidate = call(ctx, "candidate_analyse", identifiers=["FIXTURE1"], years=1, allow_network=False)
    assert candidate["status"] == "succeeded", candidate
    assert candidate["result"]["classification"] == "provisional_not_ranked", candidate
    assert candidate["result"]["status"] == "provisional", candidate
    assert candidate["result"]["rows"][0]["instrument_id"] == "FIXTURE1"
    job = call(ctx, "job_status", job_id=candidate["job_id"])
    assert job["job"].status.value == "succeeded"
    add_instrument(ctx)


def seed_proposal(ctx):
    from etf_cockpit.portfolio.paper_bots_execution import PriceBook
    from etf_cockpit.portfolio.paper_trading import PaperLedger
    from etf_cockpit.portfolio.proposal_policy import (REQUIRED_GATES, GateEvidence, ProposalRequest,
        build_proposal_decision, current_authority_policy_checksum, save_proposal_decision)
    from etf_cockpit.portfolio.costs import average_daily_value_eur, estimate_execution_cost
    from etf_cockpit.signals.friction_edge import evaluate_friction_gate
    root = ctx.session.root
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(root, account_id="l9-paper")
    bar = PriceBook.from_root(root).last_bar("VWCE", now.date(), known_by=now)
    assert bar is not None
    fingerprint = pd.util.hash_pandas_object(pd.Series([
        "VWCE", str(bar["date"]), str(bar["_known_at"]), 100.0]), index=False).astype("uint64").to_list()
    prices = pd.read_csv(Path(__file__).parent / "prices.csv")
    history = prices[(prices["etf_id"] == "VWCE") & (pd.to_datetime(prices["date"]).dt.date <= now.date())
                     & (pd.to_datetime(prices["known_at"], utc=True) <= now)]
    adv = average_daily_value_eur(history["volume"], history["close"], currency="EUR")
    cost = estimate_execution_cost(ctx.session.snapshot.config, "VWCE", 1000.0, adv_eur=adv)
    request = ProposalRequest(instrument_id="VWCE", current_quantity=0.0, target_quantity=10.0,
        strategy_id="strategy:paper_portfolio", strategy_stage="paper", model_id="model:paper", model_stage="paper",
        account_id="broker:paper_portfolio", account_stage="paper", optimiser_output_id="l9-seeded-optimiser",
        portfolio_revision=ledger.snapshot().ledger_hash, data_revision="price:" + ":".join(map(str, fingerprint)),
        as_of=now-timedelta(seconds=1), expires_at=now+timedelta(minutes=10),
        authority_policy_checksum=current_authority_policy_checksum(),
        gate_evidence=tuple(GateEvidence(name, True, "Explicit test input evidence") for name in REQUIRED_GATES),
        approvals=("paper_simulation_review",), friction_gate=evaluate_friction_gate(150.0,
            order_value_eur=1000.0, cost_estimate=cost.as_dict(), uncertainty_bps=25.0),
        event_calendar_path=root / "data" / "clean" / "event_calendar.parquet")
    decision = build_proposal_decision(request)
    assert decision.proposal_allowed, decision
    save_proposal_decision(decision, directory=root / "data" / "operations" / "proposals")
    return decision.proposal_id


def flow4(ctx):
    from etf_cockpit.portfolio.paper_trading import PaperLedger
    ranked = call(ctx, "scores_ranked", buy_eligible_only=True)
    assert ranked["rows"] == []  # Report gate-failed shortlist honestly.
    finding = research(ctx, "sentiment")
    assert PaperLedger(ctx.session.root, account_id="l9-paper").snapshot().cash == 10000.0
    source = seed_proposal(ctx)
    # Placement confirmation must refuse before reading terms or accepting a proposal.
    uncommitted = {"proposal_id": source, "instrument_id": "VWCE", "quantity": 10.0}
    confirmed(ctx, "paper_order_place", uncommitted)
    confirmed(ctx, "paper_order_place", {**uncommitted, "dry_run": False})
    args = {"account_id": "l9-paper", "instrument_id": "VWCE", "side": "buy", "quantity": 10.0,
        "rationale": "L9 sentiment evidence, conditional on all canonical gates", "evidence_refs": [finding, source]}
    preview = confirmed(ctx, "paper_order_preview", args)
    # Explicit missing-token commit attempt, in addition to the safe dry run.
    confirmed(ctx, "paper_order_preview", {**args, "dry_run": False})
    data = preview["preview"]
    assert data["status"] == "confirmation_required", data
    committed = call(ctx, "paper_order_preview", **data["confirmation_arguments"], confirm_token=data["confirm_token"])
    assert committed["status"] == "proposal_ready", committed
    terms = ctx.session.root / "data" / "operations" / "paper_order_terms" / f"{committed['proposal_id']}.json"
    assert terms.is_file() and finding in json.loads(terms.read_text())["evidence_refs"]
    place = {"proposal_id": committed["proposal_id"], "instrument_id": "VWCE", "quantity": 10.0}
    confirmed(ctx, "paper_order_place", place)
    confirmed(ctx, "paper_order_place", {**place, "dry_run": False})
    placed = call(ctx, "paper_order_place", **place, dry_run=False, confirm_token=committed["confirm_token"])
    assert placed["journal_entry_id"] and placed["fill"]["price"] == 100.0
    portfolio = call(ctx, "paper_portfolio", account_id="l9-paper")
    assert portfolio["positions"][0]["quantity"] == 10.0


def flow5(ctx):
    call(ctx, "cockpit_status")
    call(ctx, "paper_bots_status")
    health = call(ctx, "data_health", dataset="prices")
    assert health["rows"] and health["rows"][0]["row_count"] == 320, health
    assert Path(health["rows"][0]["path"]).is_relative_to(ctx.session.root)
    readiness = call(ctx, "data_readiness", start=date(2026, 10, 29), end=date(2026, 10, 30))
    assert readiness["summary"]["status"] == "FAIL", readiness
    gates = call(ctx, "gates_status")
    assert gates["data_quality"]["status"] != "passed", gates
    call(ctx, "alerts_list", limit=5)


def flow6(ctx):
    from etf_cockpit.mcp.errors import MCPToolError
    try:
        call(ctx, "ticket_preview", instrument_id="VWCE")
    except MCPToolError as exc:
        assert exc.reason_code == "TOOL_NOT_FOUND"
        raise ToolDefect("D2: owner-deferred ticket/fill lane absent from registry") from exc
    raise AssertionError("D2 status changed: implement and review the full ticket/fill flow")


if __name__ == "__main__":
    selected, root_arg = int(sys.argv[1]), Path(sys.argv[2]).resolve()
    seed(root_arg, selected)
    active = context(root_arg)
    try:
        globals()[f"flow{selected}"](active)
    except ToolDefect as defect:
        print(f"DEFECT: {defect}")
        sys.exit(23)
