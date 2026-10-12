# Issue #26 handoff

- Safe point reached: the existing direct overlap and nested look-through paths were audited with focused synthetic tests; no production gap was exposed.
- Direct overlap retains exact typed-identity matching, weighted-minimum pair overlap, and dated lower bounds for partial evidence.
- Look-through retains explicit unknown weight for unexpanded funds and derivatives without underlying evidence; synthetic totals reconcile to input weight.
- Missing holdings return `missing` status, null pair values, a reason, and full portfolio weight as unknown.
- Defaults preserved: 90-day freshness window; look-through depth defaults to 8 and remains bounded from 1 to 32. The depth test uses 1 to exercise the safe bound.
- Final acceptance remains open because issue #26 supplies no completeness criteria or owner-approved real-data acceptance artefact.
- No real-data acceptance is claimed; owner criteria are still required before expanding the scope.
