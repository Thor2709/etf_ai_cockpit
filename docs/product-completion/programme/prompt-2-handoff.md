# Prompt 2 handoff

Start from `issues/issue_registry.json`, `issues/programme_control_state.json`, `docs/product-completion/CURRENT_STATUS.json`, `docs/product-completion/PROGRESS.md`, `docs/product-completion/DELIVERY_WORKFLOW.md`, `plans/ACTIVE_CODEX_GOAL.md`, the relevant phase document and the current batch plan. Run `python scripts/generate_programme.py --root . --check` plus the focused tests and canonical classifier before implementation. Treat the reconciliation report as the evidence boundary: the package is immutable, local-only historical records are explicit, dependencies are classified, and no product feature was implemented by Prompt 1.

First implementation candidates are the records marked `ready` by the registry helper, subject to their blocking dependencies and the local-first safety policy. Re-run the atomic generator check, focused tests and classifier after changes.
