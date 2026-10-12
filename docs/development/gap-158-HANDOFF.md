# #158 safe-point handoff

- Synthetic safe-point work is implemented; real-document acceptance remains open.
- Missing field evidence now has status `unavailable` and a warning reason; missing required fields still block success.
- Parser version is 2.2 because the emitted field-evidence status changed.
- Conservative defaults: English only; the three existing prospectus, annual-report, and half-year-report templates; no generic fallback.
- Synthetic fixtures cover all registered kinds, unsupported-language rejection, and absent-evidence behavior.
- Reports remain ineligible for scoring and execution.
- Open: the owner must define accepted issuers/templates, languages, field expectations, and an approved source corpus with expected outputs.
- After that decision, extend only the agreed templates and validate against that corpus; no real-data acceptance is claimed here.
