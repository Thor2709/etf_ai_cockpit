# Norway official filing import

The supported offline route for a Norwegian equity certificate is the existing
OAM archive followed by the ESEF and statement-evidence pipeline.  For the
SpareBank 1 SMN acceptance instrument (`MING`, `NO0006390301`, organisation
number `937901003`), the owner supplies a locally retained ESEF ZIP/XBRI package
and the official NewsWeb or Finanstilsynet URL; the command never fetches a
network resource.

```text
python scripts/import_official_filing.py path/to/report.xbri --jurisdiction NO --instrument-id MING --source-url https://newsweb.oslobors.no/message/<id> --expected-period 2025-12-31 --published-at 2026-03-05 --output-dir evidence/norway/ming-2025
```

Use `--expected-sha256` for an independently pinned checksum and
`--fact-sheet path/to/ec-facts.json` for disclosed equity-certificate facts.
Each fact-sheet item must include a source locator, unit and period; omitted
items are persisted as unavailable rather than zero.  A revised package has a
new content checksum and is appended to the evidence history.

The repository fixture at
`tests/fixtures/official/esef_report_package/synthetic-ming-2025.xbri` is
explicitly synthetic and is not official financial data.
