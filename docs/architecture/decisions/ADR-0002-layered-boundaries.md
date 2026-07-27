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
