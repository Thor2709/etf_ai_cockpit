# UPDATEV2-0013 source evidence

- Source paths: `src/etf_cockpit/data/esef_provider.py`, `src/etf_cockpit/parsers/esef_ixbrl.py`, `src/etf_cockpit/parsers/sec_facts.py`, `src/etf_cockpit/app/state.py`, `src/etf_cockpit/app/pages/trust_evidence.py`.
- The parser retains raw checksum/provenance, extracts contexts/units/decimals, keeps extensions with warnings, maps only explicit IFRS concepts and preserves `execution_allowed=false`.
- Final source hash: `51fa32b5f63fd2f28572caed241db1dc6bde56e8a8e82afd452486f8471b4e1d`.
- All required local closure gates passed, and the authoritative local issue record is closed. Remote integration and GitHub issue synchronisation remain pending at this evidence checkpoint.
