# Versioned lineage registry

`etf_cockpit.core.versioning` provides the local-first version and lineage
contract for ISSUE-0075. It records semantic versions and normalised
content hashes for schemas, formulas, features, datasets, models and policy
files. Optional model weights and unavailable datasets remain explicit rather
than being represented by invented placeholders.

Each score run writes an immutable manifest containing the exact registry
signature, semantic version and content hash for every dependency. A cache is
reusable only when each recorded dependency remains available with the same
version and hash; otherwise the result is marked for rebuild with a reason.
The registry and manifests are content-addressed JSON artefacts under
`data/derived/` and contain `execution_allowed: false`.

Migrations are forward-only and return an explicit plan. Historical manifests
remain readable because they retain their original references; a mutable
`latest` alias can be used for navigation but never as historical authority.
Compatibility, deprecation, optionality and rebuild sensitivity are recorded
on each registry record.

Score runs include the score formula, feature registry, universe, portfolio
targets, risk limits, costs, model settings and strategy-scope policy in their
dependency set. This makes downstream score, forecast, target and advisory
proposal evidence reproducible without granting the manifest execution
authority.

The Diagnostics, Audit and What Changed workspaces surface the registry
version, signature, record coverage and rebuild policy. This is lineage and
reproducibility evidence only; it does not add broker execution or cloud
storage.
