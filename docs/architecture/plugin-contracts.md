# Local plugin contracts

The plugin boundary is optional and local-first. Providers, parsers, model challengers, strategies, optimisers and broker adapters use the same versioned manifest and health/result contracts.

Every manifest declares its licence, capabilities, network access, credential requirements, quota and retention policy. Registration requires an explicit allow-list and an exact version match. Entry-point discovery is opt-in and imports only allow-listed names.

Plugins receive request data and a read-only `PluginContext`. They do not receive canonical store handles, write callbacks or executable authority. Canonical imports, schema validation, audit publication and any future broker action remain core-owned. Broker adapters may report paper or read-only status only; `execution_allowed=false` remains authoritative.

Disabled or unavailable plugins are visible as capability rows and are never probed or invoked. The built-in deterministic provider and baseline model remain available when every optional plugin is disabled. `tests/test_plugin_contracts.py` is the secret-free conformance kit for manifest, allow-list, disabled-path, failure and authority checks.
