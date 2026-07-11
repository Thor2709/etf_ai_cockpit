# UPDATEV2-0022 source gate

`src/etf_cockpit/data/evidence_ledger.py` defines source authority, freshness, conflict and score eligibility. `trust_artifacts.py` writes score components, history, drivers, clusters and attribution. `trust_evidence.py` renders the ledger tables, while `simple_scores.py` exposes source/quality/authority details in expanded rows. Missing source and conflicts remain ineligible; low-authority evidence cannot become executable authority.
