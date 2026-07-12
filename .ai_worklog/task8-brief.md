# Wave 3 Task 8 brief - Canonical Data Contracts and Provider Registry

## Owning issue

- `UPDATEV2-0010` - provider registry, capability probes and source authority model.

## Binding constraints

- Preserve the approved product scope and current dark evidence-cockpit Flet vocabulary; no unrelated controls.
- `execution_allowed` remains `false`; do not add broker execution, credentials, autonomous execution or portfolio-management authority.
- Extend current provider configuration, `DataProvider` contracts and Provider Status UI. Keep offline/local-first behaviour and disabled providers safe.
- Use RED-GREEN-REFACTOR. Tests must assert observable provider states, redaction, persistence and scoring eligibility rather than private calls.
- Do not close the issue unless its complete closure dossier and all applicable closure gates pass.

## Required interfaces and outcomes

```python
class SourceAuthority(StrEnum):
    OFFICIAL = "official"
    ISSUER = "issuer"
    VENDOR = "vendor"
    COMMUNITY = "community"
    MODEL = "model"

@dataclass(frozen=True)
class ProviderCapability:
    provider_id: str
    dataset_type: str
    status: str
    authority: SourceAuthority
    configured: bool
    entitlement: str
    rate_limit_note: str
    last_success_at: str | None
    error_fingerprint: str | None
```

Registry keys must cover `yfinance`, `sec_edgar`, `filings_xbrl_org`, `fred`,
`stooq`, `rss`, `manual_local`, `issuer_document` and `index_provider`.
Every adapter exposes `probe_capabilities() -> tuple[ProviderCapability, ...]`
and lazy data methods. Disabled providers must never probe. Missing keys or
entitlements become explicit `unavailable` capability states, not exceptions.
Only `ok` capabilities may feed scoring. Official authority outranks vendor.
Serialised, logged and exported provider objects must not contain API keys,
tokens, passwords, bearer headers or `.env` values.

Persist versioned `provider_probe_results.parquet` through existing atomic I/O.
Provider Status must expose enabled/configured/status, redacted configuration,
authority, capabilities, entitlement/rate note and last success. Include
provider status in audit/export manifests where existing contracts support it.

## Required RED-GREEN-REFACTOR and verification

1. Add failing tests for disabled/no-key/ok/rate-limit/timeout/malformed probes,
   authority precedence, scoring eligibility, secret redaction and atomic
   probe-result storage.
2. Implement the smallest repository-consistent contracts, registry/adapters,
   persistence and UI extension.
3. Run focused and affected provider/trust/startup/scope tests, compileall,
   scoped Ruff, source smoke, failure-injection/redaction checks, package smoke
   and rendered Provider Status/browser evidence where changed.
4. Record exact RED/GREEN commands, outputs, checksums, migration/
   compatibility notes, independent review and any baseline limitations in
   `.ai_worklog/task8-report.md`.

## Owned files

- Create: `src/etf_cockpit/data/contracts.py`, `src/etf_cockpit/data/provider_registry.py`.
- Create: `tests/test_provider_registry.py`, `tests/test_data_contracts.py`.
- Modify: `configs/data_providers.yaml`, `src/etf_cockpit/data/providers.py`, `src/etf_cockpit/app/pages/trust_evidence.py`.
- Add only directly related tests/docs/evidence required by the observable outcomes.
