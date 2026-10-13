# Issue 246 safe-point handoff

## Implemented

- Quote evidence must identify the requested instrument; unmatched or unidentifiable records produce unavailable quote values.
- NAV identity is checked when `nav_instrument_id` or `nav_etf_id` is supplied. A separately timestamped NAV must be no later than the quote, no later than the analysis cutoff, and at most 24 hours older. When no NAV timestamp is supplied, the quote timestamp is used for the NAV in that record.
- Foreign-currency turnover can be converted with the existing point-in-time FX snapshot and cross-rate functions. The report carries the applied rate, rate date, snapshot fingerprint, status, and unavailable reason.
- Missing, stale, ambiguous, or not-point-in-time FX evidence leaves euro turnover and exchange capacity unavailable. No value is filled in.

## Conservative defaults

- FX uses the existing snapshot availability rule: only an `available` snapshot is accepted (up to three business days old); future rates and rates without verifiable `ingested_at` evidence are excluded or unavailable. A date-only decision time does not treat same-date ingestion as known during that date.
- FX conversion uses the canonical unambiguous native-currency-to-EUR cross rate. EUR turnover uses the identity rate of 1.0 and does not require FX evidence.
- NAV is linked to the quote's instrument identity unless a NAV identity is explicitly supplied. A separate NAV timestamp may be at most 24 hours older than the quote. Stale quote context remains visibly labelled by the existing quote-freshness field.

## Safe point and remaining owner work

Coverage is exercised on synthetic fixtures only. The calculator accepts optional FX evidence, but production acceptance still requires the owner to specify supported quote, NAV, and FX source artefacts and validate their identities, timing, currencies, and visible output. This work does not establish real-data acceptance, change owner settings or score weights, or authorize execution; `execution_allowed` remains false.
