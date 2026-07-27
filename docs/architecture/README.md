# Architecture documentation

This directory describes the current design of ETF AI Cockpit.

## Reading order and authority

1. [Software Design Description](SDD.md) — stable current architecture,
   boundaries, contracts, deployment and runtime interactions.
2. [Traceability](TRACEABILITY.md) — architecture families mapped to code,
   configuration, tests and canonical issues.
3. [Architecture decisions](decisions/README.md) — rationale for major
   decisions. [ADR-0070](ADR-0070-product-scope-and-authority.md) remains the
   accepted scope and staged-authority decision.
4. The [issue registry](../../issues/issue_registry.json) and
   [current-status artefact](../product-completion/CURRENT_STATUS.json) own
   issue identity, dependencies and programme state. Active
   [batch plans](../../plans/) own run state.
5. The [legacy MVP specification](../history/ETF_AI_Portfolio_Cockpit_Master_Spec_legacy.md)
   is history, not current authority.

The structure is informed by ISO/IEC/IEEE 42010 and 29148, arc42, C4 and
lightweight ADR practice; it does not claim certification to those standards.
When evidence conflicts, apply repository source precedence, label the affected
claim, and correct the SDD only after verifying code, configuration and tests.

## Audience and maintenance

The audience is product owners, maintainers, reviewers, security and release
engineers. Update the SDD and relevant ADR in the same pull request whenever a
change alters architecture boundaries, persisted schemas, public or typed
contracts, point-in-time semantics, canonical calculations, authority or trust
boundaries, deployment or packaging, or a major runtime flow. Ordinary issue
status changes belong in generated programme artefacts, not the SDD.

ADRs use the concise MADR fields in the [decision index](decisions/README.md).
Accepted records are immutable except for corrections and links; changed
decisions receive a new record and supersession link. Mermaid diagrams use
solid arrows for current calls/data flow, labelled boundaries, and explicit
`disabled` or `TARGET / PLANNED` text for non-current paths.

Traceability is maintained by architecture family rather than by duplicating
every issue. Relative links in canonical architecture documents are checked by
`tests/test_architecture_documentation.py`.
