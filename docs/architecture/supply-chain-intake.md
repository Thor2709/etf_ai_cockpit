# Supply-chain intake and provenance

`configs/supply_chain_intake.yaml` is the local registry for first-party code,
release dependencies and optional model source archives. Each record carries an
exact repository or archive reference, licence evidence, maintainers, release
cadence, tests, security policy, dependency list, copied-file declaration,
integration boundary and upstream update policy.

The registry permits dependencies and adapters, while copied third-party cores
and unreviewed vendor trees are prohibited. `scripts/check_supply_chain_intake.py`
performs a local deterministic check, records JSON and Markdown evidence, and
returns a non-zero exit code for structural failures, missing metadata or
unapproved review/signature state. It never performs network calls or enables
execution.

The optional `scripts/sign_supply_chain_intake.py` command creates a detached
HMAC-SHA256 signature using `ETF_COCKPIT_RELEASE_SIGNING_KEY`; the key is read
from the environment and is never written to the report. Settings, System Map
and audit exports expose the registry checksum, notices and component boundary
so upstream and licence hardening remains visible until approved.
