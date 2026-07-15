# UPDATEV2-0028 source gate

The current implementation assembles and validates the combined review packet in `src/etf_cockpit/chatgpt_bridge/export_pack.py`, `src/etf_cockpit/chatgpt_bridge/audit_packet.py` and `src/etf_cockpit/chatgpt_bridge/import_audit.py`, with the user-facing export state in `src/etf_cockpit/app/pages/chatgpt_audit.py`.

The audit manifest and ZIP include provider status, filing inventory, ETF-document inventory, conflict evidence, holdings evidence and candle evidence. When optional providers or market candles are unavailable, the packet contains explicit unavailable markers rather than fabricated values. External audit commentary is imported as non-executable evidence; `execution_allowed` remains `false`.
