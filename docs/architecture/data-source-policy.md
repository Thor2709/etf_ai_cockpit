# Local-first data source policy

`configs/data_source_policy.yaml` is the versioned source-of-truth for the
mandatory data boundary. Mandatory workflows may use local/user imports,
official bulk files or official cached API snapshots. Best-effort unofficial
and optional commercial sources are explicitly optional and cannot silently
become required because a provider is configured or a quota is exhausted.

The policy records licence/fair-use notes, cache paths, network optionality and
the non-blocking quota-failure rule. `scripts/check_source_policy.py` validates
the policy without contacting a provider and emits JSON/Markdown evidence. The
release gate runs this check when the policy is present.

Provider Status and onboarding expose the source tier, optionality and local
cache status. A missing cache is visible evidence; it does not trigger a
network request. This boundary preserves offline replay and keeps external
terms, throttling and credentials explicit.
