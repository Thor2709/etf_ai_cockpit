# #707 look-through safe-point handoff

The instrument detail path now requests canonical, point-in-time identity resolution. The application facade reads the existing identity projection for candidate instrument IDs and resolves each candidate through the identity master at the selected analysis date and decision time. Ambiguous, manually reviewed, future-known, or unavailable aliases do not map; strict production look-through keeps their weight unresolved. Typed-listing behavior remains available to direct calculation callers for existing synthetic workflows.

Look-through results now include an 80% minimum covered-weight threshold by default for covered-weight-normalised exposures and constituent P/E/ROIC aggregates. The threshold is configurable from 0% to 100%; an aggregate must meet it against both its mapped operating-company denominator and total portfolio weight. P/E retains the weighted earnings-yield method, ROIC retains a covered-weight arithmetic mean, and constituent metrics require a source, dated fact, known-at time, and matching unambiguous currency. Gross reported exposures, covered-weight-normalised exposures, both denominators, threshold, status, and selected holdings provenance are exposed separately. Cash, derivatives, funds, and unresolved identities remain distinct. Factor and classification buckets are explicitly labelled as provider-reported holdings dimensions; no factor score or current classification is inferred.

The ETF detail research panel shows the holdings and analysis dates, source lineage, reported and mapped weights, coverage-gated metrics, concentration, exposure coverage, formulas, limitations, and unavailable reasons. Execution remains disabled.

## Conservative defaults and safe point

- Minimum aggregate coverage: **80%** of both mapped operating-company weight and total portfolio weight. This is a conservative display gate; callers can configure a different threshold for research.
- Maximum holdings age remains the existing **90 days** default.
- Look-through is direct only. Recursive fund and derivative exposure remains unavailable.
- The identity projection supplies candidate canonical IDs. Any constituent absent from that candidate list or unresolved at the PIT cutoff stays unresolved.
- Acceptance is limited to synthetic fixtures and local machinery. A real ETF holdings-to-visible-output acceptance artefact, exact real holdings/analysis dates, and real provider coverage reconciliation remain for the release safe point.

## Synthetic chain record

The fully covered fixture uses a synthetic holding snapshot dated **2026-07-01**, known at **2026-07-02T12:00:00Z**, analyzed at **2026-07-15T16:00:00Z**. Reported provider coverage is **100%**; point-in-time identity mapping resolves **100%** to `SEC-APPLE`; unresolved, cash, derivative, and fund weights are **0%**. Its synthetic constituent fact is dated **2026-06-30**, known at **2026-07-10T10:00:00Z**, source `fundamental:SEC-APPLE`, currency USD, P/E 20, and ROIC 10%; both metric coverage fractions are **100%**. The calculated covered-weight P/E is 20 and covered-weight mean ROIC is 10%. Its sector evidence is provider-reported Technology at 100%. A separate 50%-fundamental-coverage fixture confirms that P/E and ROIC values are withheld below the default gate, while gross sector weight remains visible and the partially covered industry normalisation is withheld.

## Validation expected

Validation passed: `python -m pytest tests/test_gap_707.py tests/test_etf_look_through.py tests/test_instrument_detail.py tests/test_issue0010_instrument_detail.py tests/test_task19_instrument_detail.py tests/ui/test_page_instrument_detail.py tests/test_architecture_boundaries.py -q --tb=line -p no:cacheprovider` — **201 passed, 0 failed**, exit code 0. `git diff --check` reported no whitespace errors.
