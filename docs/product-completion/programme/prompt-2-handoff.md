# Prompt 2 handoff

Start from `issues/issue_registry.json` and `docs/product-completion/programme/roadmap.md`. Read the relevant phase document before implementing product work. Treat the reconciliation report as the evidence boundary: the package is immutable, local-only historical records are explicit, dependencies are classified, and no product feature was implemented by Prompt 1.

First implementation candidates are the records marked `ready` by the registry helper, subject to their blocking dependencies and the local-first safety policy. Re-run `python scripts/generate_issue_registry.py --check`, `python scripts/update_programme_status.py --check` and the focused tests after changes.
