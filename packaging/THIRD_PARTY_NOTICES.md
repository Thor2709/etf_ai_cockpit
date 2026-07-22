# ETF AI Cockpit third-party notices

This portable package contains the Python runtime dependencies listed in
`requirements-release.txt`. Their exact versions and package identifiers are
recorded in the release CycloneDX SBOM; the SBOM is the authoritative
machine-readable inventory shipped with each release.

The direct dependency inventory is intentionally explicit so an offline
reviewer can compare the package against the signed release manifest:

| Package group | Notice and licence evidence |
|---|---|
| Flet / flet-web | Package metadata and SBOM component |
| pandas / NumPy / PyArrow / DuckDB | Package metadata and SBOM component |
| Plotly / Pydantic / PyYAML / python-dotenv | Package metadata and SBOM component |
| requests / Rich / joblib / scikit-learn / yfinance | Package metadata and SBOM component |
| exchange-calendars | MIT; audited exchange-session/holiday dependency pinned in the release lock, used locally without runtime network access |
| cryptography | Fernet/PBKDF2 backup encryption; package metadata and SBOM component |
| pytest / Hypothesis / Ruff / mypy / pytest-timeout / pip-audit | Release-gate tooling; package metadata and SBOM component |

No third-party source is silently bundled or downloaded by the application at
runtime. Licence metadata that is absent from a package is a release-gate
failure and cannot be hidden by this summary file.

Optional TimesFM and Toto source archives are recorded separately in
`configs/supply_chain_intake.yaml`, including their local licence paths,
provenance references, copied-file boundaries and upstream update policy. They
are reference archives only; they are not imported or enabled at application
startup.
