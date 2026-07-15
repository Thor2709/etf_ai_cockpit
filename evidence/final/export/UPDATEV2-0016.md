# UPDATEV2-0016 export gate

The regenerated audit packet `data/audit_packets/audit_packet_2026-07-15.zip` passed `ZipFile.testzip() == None`. Its evidence export contains `evidence_export/fund_holdings.csv` and `evidence_export/fund_holdings.json` for the imported Vanguard issuer fixture, with the observed 3,789-row partial holding set and `score_eligible=False`; no unavailable marker is emitted for the primary CSV mirror. The package manifest and checksum manifests are present; SHA-256 is `5fb4d1f05cc2446d59ffec9cbdeca6f6b71a50f517e75dc3bd70cf7fbe36f994`.
