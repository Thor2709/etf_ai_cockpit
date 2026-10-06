# Developer guide

Release version: `1.1.0b1` (display: `1.1.0-beta.1`).

Orientation for a new contributor. The rules, checklists and clean-checkout
commands are in [CONTRIBUTING](../../CONTRIBUTING.md); the architecture is in the
[SDD](../architecture/SDD.md); the delivery process is in the
[delivery workflow](../product-completion/DELIVERY_WORKFLOW.md) and the
[control plane](CONTROL_PLANE.md). The product is local-first and
`execution_allowed=false`; do not add broker or provider writes.

## Build and test from a clean checkout

```text
python -m pip install -e ".[dev]"
python -m pytest tests -q
python scripts/run_app.py --smoke
```

Optional extras are `parsers` (filings, PDF, RSS) and the model requirements in
`requirements-models.txt`; the baseline path needs neither. `pytest` is
configured in `pyproject.toml` (`src` on the path, quiet output). Run the focused
tests for the files you touch first, then the classifier-driven scope from the
delivery workflow: `python scripts/classify_validation.py --help` and
`python scripts/validate_app.py --help` list the options.

## Repository map

| Path | Role |
| --- | --- |
| `src/etf_cockpit/app/` | Flet presentation: `router.py` (binds the `core/navigation.py` routes to page renderers; shell), `pages/`, `components/`, `theme.py`. Pages render view models and never calculate. |
| `src/etf_cockpit/application/` | Typed local application API and contracts, orchestration services (`snapshot_builder.py`, `*_service.py`), `*_views.py` read models and the `ui_facade.py` presentation facade between pages and domain code. |
| `src/etf_cockpit/core/`, `data/`, `parsers/` | Configuration, route registry (`core/navigation.py`), atomic I/O, jobs, stores, providers, backups and parsers. |
| `src/etf_cockpit/features/`, `signals/`, `analysis/`, `portfolio/`, `backtest/`, `validation/` | Domain calculations: one canonical path per financial calculation. |
| `src/etf_cockpit/models/`, `audit/`, `chatgpt_bridge/` | Optional forecast adapters and advisory audit tooling. |
| `src/etf_cockpit/governance/`, `security/`, `operations/`, `trading/` | Authority, policy gates, credentials, paper ledger and disabled broker contracts. |
| `src/etf_cockpit/plugins/` | Plugin manifest, registry and built-in plugins. |
| `configs/`, `data/` | Local configuration and runtime data. |
| `scripts/` | Command-line entry points and generators. |
| `tests/` | Pytest suite, including contract, architecture and documentation tests. |
| `issues/`, `docs/product-completion/` | Canonical programme registry and generated status (never hand-edit rendered views). |

## Add or change a page

1. Add the page module under `src/etf_cockpit/app/pages/` and register its
   route title in `ROUTE_TITLES` and its workspace in `WORKSPACE_GROUPS` in
   `core/navigation.py`, and its renderer in `_PAGE_RENDERERS` in `app/router.py`
   (`PAGES` is built from them and the router refuses a mismatch).
2. Add a short help sentence for the route to `PAGE_HELP` in
   `pages/help_glossary.py`; the command palette and navigation read the same
   registries.
3. Read data through the application API or UI facade, not from stores or
   domain modules directly; `tests/test_architecture_boundaries.py` and
   `tests/test_import_layering.py` guard the boundary. Show missing data as
   `Unavailable` or `N/A`, never zero.
4. Update [Workspaces and navigation](../user/WORKSPACES.md); the documentation
   test fails when a registered route is missing there.
5. Run the UI sweep from the delivery workflow: `tests/test_button_contracts.py`,
   `tests/test_flet_layout_contracts.py` and
   `tests/test_accessibility_contracts.py`, plus your page tests.

## Add a provider, parser, model or strategy plugin

Follow [Local plugin contracts](../architecture/plugin-contracts.md). A plugin
exposes a `PluginManifest` (`plugin_id`, `version`, `kind`, `capabilities`,
`licence`, `network_access`, `credential_requirements`, `quota`, `retention`,
`authority`) and a `health(context)` method, and is registered with
`PluginRegistry.register` against an explicit allow-list. Manifests cannot
request canonical-store writes or executable authority. Add the conformance
checks from `tests/test_plugin_contracts.py` for your plugin and keep the
built-in deterministic provider and baseline model working with every optional
plugin disabled.

## Calculations, data and persistence

- Keep each financial calculation on its existing canonical path; extend it
  instead of adding a second formula. Methodology pages are listed in the
  [methodology index](../reference/methodology-index.md).
- Use adjusted, corporate-action-aware prices; point-in-time and revision
  semantics apply to every time filter (bounded by decision time and by the
  active window). Do not zero-fill, forward-fill missing evidence or use future
  observations.
- Persisted formats are described in the generated
  [data dictionary](../reference/data-dictionary.md) and the
  [storage migration plan](../architecture/local-storage-migration-plan.md).
  A schema change needs a migration, a rollback path and a test.

## Documentation and generated files

| Command | Purpose |
| --- | --- |
| `python scripts/generate_data_dictionary.py` | Regenerate `docs/reference/data-dictionary.md` (`--check` reports drift). |
| `python scripts/generate_application_api_docs.py` | Regenerate the application API documents (`--check` reports drift). |
| `python scripts/generate_programme.py --root . --check` | Verify rendered programme views are current. |

Documentation tests: `tests/test_documentation_integrity.py` (links, commands,
generated drift, version) and `tests/test_user_documentation.py` (workspace
coverage, on-screen labels, methodology index, version stamps),
`tests/test_architecture_documentation.py`. Every documented
`python scripts/<name>.py` command must exist and, when it builds an argument
parser, answer `--help`. When the release version in `pyproject.toml` changes,
update the `Release version` line of each stamped page after reviewing it.

## Review

Use the checklists in [CONTRIBUTING](../../CONTRIBUTING.md). Programme-control,
financial, persistence, concurrency, security and release changes need the
independent reviews and full gates described in the delivery workflow.
