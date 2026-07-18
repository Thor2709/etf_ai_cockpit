# Programme Map

The `/roadmap` page is a read-only projection of `issues/issue_registry.json`.
It renders each canonical issue with independent dimensions for implementation,
registry package status (release), required data inputs, separately declared
model authority, paper authority and live authority. The page does not infer
readiness from route existence, issue prose or a related issue.

Paper and live authority are disabled by the product authority matrix. A
missing or malformed canonical registry fails closed and displays no issue
readiness. The release value is the source registry's package status only; it
is not a release certification result. Certification remains the responsibility
of Release Readiness and its evidence gates.
