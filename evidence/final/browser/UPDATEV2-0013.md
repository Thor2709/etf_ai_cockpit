# UPDATEV2-0013 browser evidence

- Fresh source UI started on port 8932 and rendered the Simple Scores dashboard and `/filings` route in the Codex browser.
- Fresh packaged native UI started from `build/ETF_AI_Cockpit_Portable_v0.1.0rc1/native/ETF_AI_Cockpit/ETF_AI_Cockpit.exe` on port 8945 and rendered `/filings`; screenshot `browser/UPDATEV2-0013-filings-packaged.png` is checksum-recorded.
- The packaged `/filings` screenshot shows the ESEF import workflow, warning/unavailable text and disabled broker execution state. HTTP source and native smoke plus rendered source and packaged observations passed.
