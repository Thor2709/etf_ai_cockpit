# Software supply-chain and offline update controls

`ISSUE-0145` adds a local supply-chain evidence boundary around the release
gate. `scripts/supply_chain_scan.py` records the exact dependency lock, a
CycloneDX SBOM, tracked-source secret findings, package licence metadata,
`pip-audit` vulnerability output and the packaged third-party notice file.
Missing licence metadata, credential-like source content, an unavailable
mandatory scanner or any unapproved vulnerability blocks the scan. Approved
mitigations must identify the vulnerability explicitly in
`configs/supply_chain_policy.yaml`. The policy also records dependency
cooldown, emergency-patch and end-of-life decisions for release review.

`etf_cockpit.core.secure_update` verifies an offline ZIP before staging it:
the archive hash, exact member set, per-file hashes, path safety and detached
HMAC-SHA256 signature all have to match. Directories, duplicate entries,
symbolic links, path traversal and oversized members are rejected. Verification
does not replace the running application; it creates an isolated staging tree
for a separately reviewed promotion step.

The Settings page shows release-evidence status, version and third-party notice
availability. No network retrieval, broker automation, credentials or live
order authority is introduced. The HMAC control is an offline shared-key
release boundary; public-key signing and broader dependency lifecycle policy
remain explicit follow-up hardening where required.
