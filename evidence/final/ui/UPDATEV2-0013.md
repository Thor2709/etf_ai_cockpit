# UPDATEV2-0013 UI evidence

- Source UI smoke: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe scripts/smoke_app.py --mode source --port 8931 --timeout 60` → `smoke_ok` and HTTP readiness passed.
- Fresh rendered source screenshot: `browser/UPDATEV2-0013-filings-source.png`.
- The Filings & Statements route visibly exposes SEC/ESEF/local import, country and filing-ID fields, discovery/download controls, authority state, unavailable-state text and broker-execution-disabled semantics.
