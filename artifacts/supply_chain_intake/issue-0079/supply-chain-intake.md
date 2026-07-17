# Supply-chain intake report

- Schema: `supply-chain-intake.v1`
- Status: `passed`
- Review status: `hardening_required`
- Registry SHA-256: `1bf5e532b576cda16bcbf74c2bca98c7f2e251315e317a477c60c7ea0816d325`
- Components: `4`; locked dependencies: `23`
- Network calls: `false`
- Execution allowed: `false`
- Duration: `78.79 ms`

## Failures

- None

## Hardening required

- upstream repository, maintainer, cadence and licence evidence still require human approval
- one or more intake records remain hardening_required
- one or more component licence classes remain unclassified
- copied source archives remain subject to approved provenance and upstream-diff review: timesfm_source_archive, toto_source_archive
- locked dependencies require licence, repository or maintainer metadata review: build, cryptography, duckdb, flet, flet-web, hypothesis, joblib, mypy, numpy, pandas, pip-audit, plotly, pyarrow, pydantic, pytest, pytest-timeout, python-dotenv, requests, rich, ruff, scikit-learn, yfinance
- detached intake signature status is missing

## Locked dependency metadata

| Package | Version | Licence | Class | Repository | Maintainer |
|---|---|---|---|---|---|
| `flet` | `0.85.3` | `Apache-2.0` | `permissive` | `unavailable` | `unavailable` |
| `flet-web` | `0.85.3` | `Apache-2.0` | `permissive` | `unavailable` | `unavailable` |
| `pandas` | `2.3.3` | `BSD 3-Clause License   Copyright (c) 2008-2011, AQR Capital Management, LLC, Lambda Foundry, Inc. and PyData Development Team  All rights reserved.   Copyright (c) 2011-2023, Open source contributors.   Redistribution and use in source and binary forms, with or without  modification, are permitted provided that the following conditions are met:   * Redistributions of source code must retain the above copyright notice, this    list of conditions and the following disclaimer.   * Redistributions in binary form must reproduce the above copyright notice,    this list of conditions and the following disclaimer in the documentation    and/or other materials provided with the distribution.   * Neither the name of the copyright holder nor the names of its    contributors may be used to endorse or promote products derived from    this software without specific prior written permission.   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE  FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL  DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR  SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,  OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.` | `permissive` | `unavailable` | `unavailable` |
| `numpy` | `2.4.4` | `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` | `permissive` | `unavailable` | `Travis E. Oliphant et al.` |
| `pyarrow` | `25.0.0` | `Apache-2.0` | `permissive` | `unavailable` | `unavailable` |
| `duckdb` | `1.5.4` | `unavailable` | `unknown` | `unavailable` | `DuckDB Foundation` |
| `plotly` | `6.9.0` | `unavailable` | `unknown` | `unavailable` | `unavailable` |
| `pydantic` | `2.13.4` | `MIT` | `permissive` | `unavailable` | `unavailable` |
| `PyYAML` | `6.0.3` | `MIT` | `permissive` | `https://pyyaml.org/` | `Kirill Simonov` |
| `python-dotenv` | `1.2.2` | `BSD-3-Clause` | `permissive` | `unavailable` | `unavailable` |
| `requests` | `2.34.2` | `Apache-2.0` | `permissive` | `unavailable` | `unavailable` |
| `rich` | `15.0.0` | `MIT` | `permissive` | `unavailable` | `Will McGugan` |
| `joblib` | `1.5.3` | `unavailable` | `unknown` | `unavailable` | `unavailable` |
| `cryptography` | `49.0.0` | `Apache-2.0 OR BSD-3-Clause` | `permissive` | `unavailable` | `unavailable` |
| `scikit-learn` | `1.9.0` | `unavailable` | `unknown` | `unavailable` | `unavailable` |
| `yfinance` | `1.5.1` | `unavailable` | `unknown` | `unavailable` | `unavailable` |
| `pytest` | `9.1.1` | `MIT` | `permissive` | `unavailable` | `Brianna Laugher, Bruno Oliveira, Floris Bruynooghe, Freya Bruhin, Holger Krekel, Others (See AUTHORS), Ronny Pfannschmidt` |
| `hypothesis` | `6.156.6` | `unavailable` | `unknown` | `unavailable` | `unavailable` |
| `ruff` | `0.15.20` | `MIT` | `permissive` | `https://docs.astral.sh/ruff` | `unavailable` |
| `mypy` | `1.20.2` | `MIT` | `permissive` | `unavailable` | `unavailable` |
| `pytest-timeout` | `2.4.0` | `unavailable` | `unknown` | `unavailable` | `unavailable` |
| `pip-audit` | `2.10.1` | `unavailable` | `unknown` | `unavailable` | `unavailable` |
| `build` | `1.3.0` | `unavailable` | `unknown` | `unavailable` | `unavailable` |
