# Contributing

## Clean-checkout setup and checks

See the [developer guide](docs/development/DEVELOPER_GUIDE.md) for the repository map and how to add pages and plugins.

From the repository root with Python 3.11 or newer:

```text
python -m pip install -e ".[dev]"
python -m pytest tests -q
```

Run the focused tests for each fix before opening a review. Generated reference files are checked with:

```text
python scripts/generate_data_dictionary.py --check
python scripts/generate_application_api_docs.py --check
```

## Contribution checklist

- [ ] Keep operation local-first; `execution_allowed` remains `false`.
- [ ] Preserve missing values as unavailable; never zero-fill missing financial data.
- [ ] Use point-in-time evidence and avoid look-ahead or survivorship leakage.
- [ ] Keep each financial calculation on its existing canonical calculation path.
- [ ] Add or update focused tests for every fix.
- [ ] Regenerate reference documentation after every contract change.
- [ ] Use synthetic or redacted examples; do not include secrets.

## Review checklist

- [ ] Confirm local-first boundaries and `execution_allowed=false` remain intact.
- [ ] Check that missing data is not zero-filled and that no look-ahead enters a calculation.
- [ ] Check point-in-time bounds and the canonical calculation path for affected financial logic.
- [ ] Confirm each fix has focused tests and generated documentation has no drift.
- [ ] Check examples and fixtures for secrets.

## Documentation cadence

Regenerate the data dictionary and API documentation on every application contract change. The documentation integrity tests run both generators in drift-check mode and fail when checked-in output is stale.
