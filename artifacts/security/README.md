# Security findings register

`findings.json` is the release-blocking security findings inventory read by
`etf_cockpit.security.policy.build_security_report` (release gate `security_policy`).

- It must exist and be a JSON list; a missing or invalid file fails the gate closed (`evidence_unavailable`).
- Every open security finding is listed as `{"id", "severity", "status", "summary"}`; findings at a blocking
  severity block the release until their status is resolved per `configs/security_policy.yaml`.
- An empty list is an explicit, reviewed statement that no security finding is open. Update it in the same
  change that opens or resolves a finding.
