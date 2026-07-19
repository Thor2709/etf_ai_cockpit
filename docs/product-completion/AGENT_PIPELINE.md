# Agent Pipeline

This repository uses a flat, evidence-led pipeline for continuous issue delivery.

- The root agent owns architecture, shared interfaces, canonical registries, generated programme evidence, final decisions and integration.
- Native Codex subagents are optional and bounded: normally one read-only scout and one release steward, with isolated writers only for disjoint file sets. No child may spawn another child.
- A feature is frozen in a checkpoint commit before release hand-off. The steward verifies the base SHA, checkpoint SHA, changed-path allowlist, checks and authorised baseline fingerprints before pushing or merging.
- Programme-status generation must start from the latest verified `origin/main`, compare the complete status map against the last-good map, validate exact transitions/counts/checksums and regenerate derived documents together. A fresh timestamp does not make an incorrect map valid.
- Release stops for an unexpected issue transition, downgrade, file, changed head, merge conflict, ambiguous failure or product-code correction; the root then investigates and records evidence.
- GitHub issue synchronisation is checksum-gated: apply only the reviewed plan, verify readback, and finish with a no-op dry run.
- Superpowers skills, workflows, controllers and related content are prohibited. Ordinary non-Superpowers tools, plugins and MCP integrations remain allowed.
