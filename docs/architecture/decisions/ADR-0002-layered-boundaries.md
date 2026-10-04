# Layered dependency boundaries

**Status:** accepted

**Date:** 2026-07-27

## Context

The Flet UI, calculations, persistence and providers must evolve without
creating page-local financial logic or infrastructure-dependent domain rules.

## Decision

Presentation consumes typed application facades/view models. Application
orchestrates domain services and ports. Domain calculations do not import Flet
or concrete persistence/providers. Infrastructure implements local ports.
Compatibility modules are transitional and remain visible as debt.

## Consequences

Boundary tests are release evidence; new public contracts require versioning
and architecture documentation.

## Alternatives

Direct page-to-store access and a single undifferentiated package were rejected
because they duplicate calculations and impede testing.

## Evidence and links

[Application API](../application-api.md), `src/etf_cockpit/application/`,
`tests/test_architecture_boundaries.py`.

## Implementation status (2026-10-04)

Code moved to the layers above without behaviour change ([layer map](../SDD.md)); `tests/test_import_layering.py`
enforces it and layer-breaking import edges fell from 84 (baseline `5e501154`) to 19. Seven are accepted by design:
- `core.config` -> `data.universe_store`: config loader overlays the persisted universe revision.
- `core.config` -> `security.credentials`: provider settings resolve vault-held credentials.
- `core.job_scheduler` -> `data.local_storage`: durable scheduler persists jobs in local storage.
- `core.migrations` -> `operations.recovery`: startup migrations run the recovery journal.
- `core.session_log` -> `operations.event_store`: session trace is written through the event store.
- `data.sec_edgar_provider` -> `application.sec_bulk_import`: provider-owned SEC session seam (lazy).
- `data.sec_edgar_provider` -> `application.sec_submissions_import`: provider-owned SEC session seam (lazy).

Compatibility debt: 12 `KNOWN_VIOLATIONS` (`app/state.py`, `app/pages/onboarding.py` import data/domain modules directly).
The 5 compatibility-only modules (`services`, `app.operations`, `app.selectors.instrument_detail`, `application.screening`,
`signals.research_states`) were removed in P9b, after their last consumer moved to the canonical module.
