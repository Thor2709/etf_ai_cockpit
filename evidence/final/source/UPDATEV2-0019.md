# UPDATEV2-0019 source evidence

Task 15 implements index-methodology extraction in `src/etf_cockpit/parsers/index_methodology.py`, persistence through the parsed-disclosure and fund-document stores, ETF Disclosures presentation and audit CSV/JSON export. Version/date/provider/rules/cap fields remain checksum-backed; holdings comparison is a separate availability/manual-review signal and cannot erase a valid source-document path. The current source verification hash is `13e8d244c4360baa44d44b1bac61d5d59b3ccd5eb27a19b9b4604b3daff9c9d0`.

Authority remains unchanged: methodology is high-authority evidence for target-index rules, does not alter score weights or portfolio authority, and cannot enable execution. Implementation originated in PR 185 (`9139e515bda9e149dde52e9074990cbc5c781e84`), with the closure fixes on this branch pending integration.
