# ETF AI Cockpit third-party notices

This portable package contains the Python runtime dependencies listed in
`requirements-release.txt` and `requirements-release-parsers.txt`. Their exact versions and package identifiers are
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
| exchange-calendars | Apache-2.0; audited exchange-session/holiday dependency pinned in the release lock, used locally without runtime network access |
| cryptography | Fernet/PBKDF2 backup encryption; package metadata and SBOM component |
| arelle-release[esef] / Pillow / pdfplumber / defusedxml / feedparser / pypdf | Parser dependencies; package metadata and SBOM components from the parser release lock |
| Optional `quant` extra: skfolio / arch / statsmodels / LightGBM / SciPy | BSD-3-Clause (skfolio, statsmodels, SciPy), NCSA (arch), MIT (LightGBM); not in the release lock or the SBOM; recorded in `configs/supply_chain_intake.yaml` |
| Optional `sec` extra: edgartools / lxml | MIT (edgartools 6.1.0), BSD-3-Clause (lxml 6.1.3); edgartools is not in the release lock or the SBOM; lxml is pinned in the parser lock; recorded in `configs/supply_chain_intake.yaml` |
| Optional `retrieval` extra: fastembed + local weights Qdrant/bge-small-en-v1.5-onnx-Q (ONNX conversion of BAAI/bge-small-en-v1.5) | Apache-2.0 (fastembed 0.9.1), MIT (weights); not in the release lock or the SBOM; weight files pinned by sha256 in `configs/supply_chain_intake.yaml` |
| pytest / Hypothesis / Ruff / mypy / pytest-timeout / pip-audit | Release-gate tooling; package metadata and SBOM component |

No third-party source is silently bundled or downloaded by the application at
runtime. Licence metadata that is absent from a package is a release-gate
failure and cannot be hidden by this summary file.

Optional TimesFM and Toto source archives are recorded separately in
`configs/supply_chain_intake.yaml`, including their local licence paths,
provenance references, copied-file boundaries and upstream update policy. They
are reference archives only; they are not imported or enabled at application
startup.
