# Agent Pipeline

This repository uses a flat, evidence-led pipeline for continuous issue delivery.

- The root agent owns architecture, shared interfaces, canonical registries, generated programme evidence, final decisions and integration.
- Native Codex subagents are optional and bounded: normally one workspace-writing child and at most two children total. A second child is read-only unless proven-disjoint worktrees and file ownership make concurrent writes safe. No child may spawn another child.
- A feature is frozen in an exact-head checkpoint before release hand-off. The root verifies base/head identity, changed-path allowlist, checks and authorised evidence before pushing or merging. The detailed E/O/H/C, cadence and gate contract is [`DELIVERY_WORKFLOW.md`](DELIVERY_WORKFLOW.md).
- Programme-status generation must start from the latest verified `origin/main`, compare the complete status map against the last-good map, validate exact transitions/counts/checksums and regenerate derived documents together. A fresh timestamp does not make an incorrect map valid.
- Release stops for an unexpected issue transition, downgrade, file, changed head, merge conflict, ambiguous failure or product-code correction; the root then investigates and records evidence.
- GitHub issue synchronisation is checksum-gated: apply only the reviewed plan, verify readback, and finish with a no-op dry run.
- Superpowers skills, workflows, controllers and related content are prohibited. Ordinary non-Superpowers tools, plugins and MCP integrations remain allowed.
