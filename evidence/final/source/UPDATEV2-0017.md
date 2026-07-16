# UPDATEV2-0017 source evidence

Task 15 implements PRIIPs KID extraction in `src/etf_cockpit/parsers/priips_kid.py`, persistence through the parsed-disclosure and fund-document stores, ETF Disclosures/Instrument Detail presentation, and audit CSV/JSON export. Identity mismatches retain parsed fields for audit while setting `manual_review=true` and `score_eligible=false`; missing, malformed, stale, unsupported-language or incomplete evidence remains explicitly unavailable/manual-review. The current source verification hash is `13e8d244c4360baa44d44b1bac61d5d59b3ccd5eb27a19b9b4604b3daff9c9d0`.

Authority remains unchanged: KID evidence is retail-product cost/risk evidence, does not substitute for holdings or prospectus evidence, does not change score weights, and cannot enable execution. Implementation originated in PR 185 (`9139e515bda9e149dde52e9074990cbc5c781e84`), with the closure fixes on this branch pending integration.
