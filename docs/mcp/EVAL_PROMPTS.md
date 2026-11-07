# MCP tool-selection evaluation prompts

Use these owner prompts to evaluate whether a client selects the intended tools
and stops at confirmation or policy gates. All runs use a fixture root and paper
execution only; unavailable evidence must remain unavailable rather than become 0.

1. **Add an instrument:** “Add iShares Core MSCI World to my local universe, refresh its prices, run the score pipeline, and explain coverage gaps.” Expected sequence: `instrument_lookup` → `universe_change_preview` → owner confirmation → `universe_change_commit` → `data_refresh` → `job_status` → `pipeline_run` → `score_explain`. Refresh must be local/fixture-only; no network access.
2. **Rank and research:** “Find the best names according to the app and research their latest evidence.” Expected sequence: `scores_ranked` → `score_explain` per result → `instrument_detail` → `forecast_get` → owner-supplied external research → `research_findings(prepare_items=...)` → owner confirmation → `research_record_findings`. Preserve unavailable scores and separate external evidence from app evidence.
3. **Assess web candidates:** “Assess these companies I found online and show which are not in the configured universe.” Expected sequence: `instrument_lookup` per name → `score_explain` for in-universe names or `candidate_analyse` for outside names → offer `universe_change_preview` only for selected additions. Candidate output stays provisional and is never ranked.
4. **Sentiment paper trade:** “Use app ratings and sentiment to propose a paper investment in the strongest eligible name.” Expected sequence: `scores_ranked` → `research_findings` → shortlist after gates → `paper_order_preview` → owner confirmation → `paper_order_place` → `paper_portfolio`. Gate failures must stop the order; no live order or broker write is allowed.
5. **Check operations:** “Check bots, freshness, readiness, gates and alerts, then summarise next actions.” Expected sequence: `cockpit_status` → `paper_bots_status` → `data_health` → `data_readiness` → `gates_status` → `alerts_list`. Report unavailable data explicitly and keep each result within the 8,000-token budget.
6. **Prepare a real order record:** “Prepare a non-executable ticket for my review, then record a fill only after I place it myself.” Expected sequence: `ticket_preview` → owner confirmation → `ticket_export` → owner acts at broker → `fill_record_preview` → owner confirmation → `fill_record_commit` → `portfolio_reconcile`. `execution_allowed` remains false. These tools are currently unavailable and this prompt is retained as an evaluation gap.


L9 correction coverage (MCP-L9-fix2)

The executable flows live in `tests/mcp/test_flows.py` and
`tests/mcp/fixtures/run_flows.py`. Each starts a fresh Python process with
`ETF_COCKPIT_ROOT` set before application imports. Independent flow processes
can run concurrently under `pytest -n auto`; each owns its data, ledger,
confirmation store, quota database and durable jobs. No agents are spawned.

Fixture inputs are explicitly test-only: 320 adjusted OHLCV rows, the same
candidate history retained by the canonical binding writer, a configured
universe, an open paper account, and policy-validated proposal input evidence.
Missing fundamentals, forecasts, holdings and research authority stay missing.
All tool steps use `invoke_tool`; job submission/execution, universe writes,
research persistence, proposal persistence and acceptance use canonical services.
Fixture setup uses the canonical universe, price, candidate and paper stores.

Remaining stubs are `identity_get_json` (Yahoo search HTTP),
`identity_post_json` (OpenFIGI HTTP) and `identity_ticker` (Yahoo profile client).
These avoid network access while preserving canonical checksum, name-agreement
and resolution logic. External web/sentiment evidence is supplied fixture input,
not a fabricated research-store result. Optional model weights are disabled.

Before every missing/invalid confirmation attempt, the flows snapshot business
files and durable workflow records, then assert that both are unchanged.
Successful universe and research commits are read back from canonical stores;
proposal/order commits and portfolio readback are asserted when gates permit.
Every returned response is normalised and checked against the section-2
8,000-token budget using a conservative estimate of 4 JSON characters/token
(32,000 characters). Execution flags are recursively required to remain false.

DEFECTS (strict xfail; unexpected errors still fail)

- Flow 1: `tools_data._submit_workflow` omits the required
  `HeadlessSession.submit_workflow(..., dedupe_key=...)` argument. Confirmed
  refresh raises `TypeError` before any workflow is submitted. The test still
  exercises the independent canonical score pipeline and score explanation.
  Refresh completion remains unmet; no completed refresh is fabricated.
- Flow 4: `preview_manual_paper_order` calls the cost estimator without ADV.
  Capacity is therefore unavailable and the canonical liquidity gate blocks
  even a bound proposal fixture. No cost/gate replacement is permitted.
  Valid proposal commit, placement and portfolio round trip remain blocked;
  missing/invalid proposal-preview commit attempts must leave state unchanged.
- Flow 6 stays deferred by owner decision D2: ticket/fill tools are absent.

Validation note: the correction session encountered a sandbox `PermissionError`
while xdist created its pytest temp directory. Final pytest counts and parallel/
serial equivalence require an outside-sandbox rerun of the packet's named checks.
Read-only reproductions confirmed the refresh signature mismatch, missing ADV
capacity and canonical fixture price validation; these are not pytest passes.
