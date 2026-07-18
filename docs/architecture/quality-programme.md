# Quality programme

`scripts/quality_programme.py` is the local-first ISSUE-0143 entry point. It
runs deterministic source suites for visual/UI contracts, performance budgets,
bounded workflow repetition, fault injection and the fail-closed chaos
sandbox:

```text
python scripts/quality_programme.py
```

The command writes `artifacts/quality/latest/quality-programme.json` and
`artifacts/quality/latest/quality-programme.md`. Every suite records its
command, status, exit code, elapsed time and bounded output. A required suite
failure or timeout returns a non-zero exit code. Reports state that network
calls and live orders are disabled.

This is the initial usable programme, not final certification. Packaged
browser journeys and reviewed visual baselines, long-duration memory and
file-descriptor soak runs, and infrastructure or live-broker chaos remain
`hardening_required`. The Release Readiness page shows the last report without
starting tests or network activity.
