# Protected release gate

`ISSUE-0013` and `UPDATEV2-0029` are implemented by `scripts/release_gate.py`.
The command is the release evidence boundary: a mandatory check failure returns
non-zero, while the JSON and Markdown evidence is still written for diagnosis.

The gate records a pinned Python version, an exact direct-dependency lock,
normalised source-file hashes, full pytest output, package build output, a
packaged offline smoke result, a deterministic CycloneDX 1.5 SBOM covering the
source manifest and packaged artifact manifest, and a detached HMAC-SHA256
release-manifest signature. The signing key is read only
from `ETF_COCKPIT_RELEASE_SIGNING_KEY`; it is never written to the evidence.
The shared-key signature is an offline local release control, not a public-key
distribution system. Public-key signing, vulnerability policy and secure
update promotion remain the separate `ISSUE-0145` scope.

The protected GitHub workflow uses Windows Python `3.12.10`, installs
`requirements-release.txt`, runs the Windows package builder and uploads the
machine-readable evidence. Pull requests may produce unsigned diagnostic
evidence; pushes to `main` require the protected signing secret.

For local diagnostics, `--skip-tests`, `--skip-package`, `--skip-smoke`,
`--allow-dirty` and `--allow-unsigned` are explicit and make the corresponding
check non-mandatory. They must not be used by a release promotion job.
