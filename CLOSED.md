# Closed Issues Index

Canonical closed/rejected/research tracker: `issues/closed.md`.

This root file exists because some research/update prompts refer to `CLOSED.md`. Keep detailed closure records in `issues/closed.md`; this file is a navigational index and coverage checklist.

## updatev2.md Research Closures

`C:\Users\thor2\Downloads\updatev2.md` added six research-only closures. These close research conclusions only. Implementation remains open in `issues/open.md` as `UPDATEV2-xxxx`.

```text
CLOSED-RESEARCH-001 Candle evidence research complete
CLOSED-RESEARCH-002 CrossCompatibleInvestmentApp review complete
CLOSED-RESEARCH-003 Provider API research complete
CLOSED-RESEARCH-004 US filings research complete
CLOSED-RESEARCH-005 European filings research complete
CLOSED-RESEARCH-006 ETF disclosure research complete
```

## Current Closure Rule

Research closures do not imply code exists. Implementation issues may move to `issues/closed.md` only after source changes, UI visibility where relevant, tests, rebuild/smoke evidence and remaining limitations are recorded.

## 2026-07-09 Run-Specific Closures

Narrow closure records added in `issues/closed.md`:

```text
RUN-CLOSED-2026-07-09-LAUNCHER Windows launcher/build/start/browser-open workflow
RUN-CLOSED-2026-07-09-SPAREBANKEN-DATA Sparebanken universe data group
RUN-CLOSED-2026-07-09-SPAREBANKEN-UI Main page Sparebanken grouping
```

These records do not close the broader selected product issues or strict parser/provider issues.

The launcher closure received post-review evidence on 2026-07-10: a dual-lock stress rebuild selected timestamped native and portable folders, launched the selected package, passed HTTP/browser smoke and passed the full 131-test suite.

Evidence-backed implementation closures on 2026-07-10:

```text
ISSUE-0035 Data health centre (current evaluator-backed closure)
```

Final current-package closures on 2026-07-11:

```text
ISSUE-0069 Single-file session action logging and diagnostics trace
UPDATEV2-0022 Evidence ledger and score component audit trail
UPDATEV2-0028 Report/audit packet expansion for providers, filings, ETF docs and candles
```

Their prior rejected checkpoints remain retained for audit history, but the current matrix status is `closed`. SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index-methodology and provider-backed workflows remain open under the strict parser/provider rule.

Each has a checksum-backed dossier under `evidence/final/issues/`. SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index-methodology and provider-backed workflows remain open under the strict parser/provider rule.
