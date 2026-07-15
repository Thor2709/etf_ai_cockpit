# UPDATEV2-0015 export gate

The audit packet `data/audit_packets/audit_packet_2026-07-15.zip` was regenerated after the Task 14 source fix and inspected with `ZipFile.testzip()`; it returned `None`. It contains `evidence_export/fund_documents.csv`, `evidence_export/fund_documents.json`, `evidence_export/fund_holdings.csv`, `evidence_export/fund_holdings.json`, the audit and checksum manifests, and explicit unavailable records for missing optional stores. This is the truthful inventory state for the issuer fixture; no document or source authority is fabricated.

SHA-256: `5fb4d1f05cc2446d59ffec9cbdeca6f6b71a50f517e75dc3bd70cf7fbe36f994`.
