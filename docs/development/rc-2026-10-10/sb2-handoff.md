# SB2 handoff (branch ui/sb2, worktree C:/dev/etf-UI-SB2, data copy C:/dev/release/sb2live)

Status: items 1-6 delivered; execution_allowed=false throughout; no push. Repo data untouched; sb2live only.

## Per item
1. Book docs: docs/architecture/sparebank-book-gap-2026-10.md + sparebank-book-manifest.md (338 equations, 27 tables, 16 rules;
   regenerated after items 3/5: R-12 partial, R-14/R-16 implemented, R-15 partial, R-13 unimplemented). Certification test green.
2. Calculations (book_calcs.py, bank_economics.py, valuation.py, claim.py, scorecard.py): lending economics, capital allocation,
   normalised ROE, credit migration, funding, reverse valuation, with goldens. Formula `sparebank-scorecard-v1.2.0`.
3. Data: HELG/RING/SOAG extension mappings (configs/esef_extension_concepts.yaml) + equity-member pools; Pillar 3 extractor +
   pending confirm/reject queue (data/pending/pillar3/<ID>.json); derived EC result/count (labelled `derived`); dividend history
   from price parquet; Euronext-listing universe sync (+ISIN fixes only for records lacking a valid ISIN, sb2live only);
   peer summary store; quarterly score history.
4. Calibration: anchors reviewed in the YAML (book citations), version bumped, refresh + rescore run on sb2live.
5. UI: Fundamentals tab bank workspace (src/etf_cockpit/app/pages/_sparebank_view.py, kit components, no raw dict except the
   audit Disclosure): summary, axes with reasons, ownership passport, bank economics, valuation, dividends, score history chart,
   peers (+pick), Pillar 3 confirm/reject, structural, marketability, tactical. Scores table/side panel: bank rows show a tagged
   "n/a" with a tooltip (not "-") and a side-panel note naming composite, coverage, missing axes and gates.
   Frozen-control bug: the raw peer TextField broke the page ("Frozen controls cannot be updated"); fixed by using the kit
   `Field(control=TextField(**field_input_style()))` idiom. Verified in the live app.
6. Smoke on port 8601 (sb2live): Home (Sparebanken chip + bank rows), Scores (25 Sparebanken, NONG side panel), NONG and HELG
   Fundamentals all render, no errors in log; app stopped, viewport reset.

## Composite / coverage, before -> after (sb2live)
AURG 6.5/0.30 -> 5.0/0.77 | HELG -/0.10 -> 4.9/0.62 | MING 6.7/0.35 -> 8.3/0.83 | MORG 6.7/0.30 -> 7.6/0.77
NONG 7.1/0.30 -> 8.6/0.77 | RING -/0.22 -> 8.3/0.69 | SOAG -/0.20 -> 6.4/0.77 | SPOG 5.6/0.25 -> 7.8/0.69 | SPOL 6.4/0.25 -> 7.1/0.77
Still no composite (coverage < 0.25 floor): HSPG, SOGN, JAEREN, MELG, SKUE 0.06 (no filing found); ROGS, SB1NO 0.12; SNOR 0.00.
AASB, BIEN, GRONG, HGSB, NISB, SB68, TINDE, TRSB: no filing, rescore refused (financial_evidence_invalid), shown as unavailable.

## Tests
sparebank*, simple_scores, architecture, layout, button, accessibility: see commit (orchestrator run)

## Pending Pillar 3 figures awaiting owner confirmation (never counted until confirmed; Fundamentals tab > Pillar 3)
NONG 6 (CET1 16.8, deposit/loan 58.2, LCR 147.0 and 146.8, leverage 7.83, NSFR 120.0; period 2024-12-31),
MING 5 (CET1 18.3, deposit/loan 57.0, LCR 183, leverage 7.0 for 2023, NSFR 125; several flagged header_not_found: check),
SPOG 11 (e.g. CET1 18.59, LCR 363.9/319.5/362.59, leverage 8.73; three CET1 requirement values need picking).
Duplicate metrics per bank: confirm one (confirming supersedes the other).

## Remaining gaps (with reasons)
- R-13 quarterly report import: no free structured source; only the PDF flow exists.
- Five non-ESEF banks: no Pillar 3 PDF has been downloaded (packet allows named official sources only); extractor ready.
- Ownerless-capital distributions (payout symmetry): not published in a free structured source.
- Structural transition and portfolio context axes have no inputs by design (owner-recorded events; portfolio not linked).
- Peers/history panels are empty when the app as-of precedes the run date (point-in-time filter; app as-of showed 8 Oct, runs 9 Oct).
- Eight universe banks have no ESEF filing (above).

## Owner decisions needed
1. Confirm/reject the pending Pillar 3 figures (22).
2. Name the official PDF URLs (or allow IR-site downloads) for HSPG, SOGN, JAEREN, MELG, SKUE.
3. Accept formula v1.2.0 re-anchoring (scores moved: NONG +1.5, MING +1.6, SPOG +2.2, AURG -1.5).
4. ISINs: in ui/rc MORG is NO0012483207 and AURG/SOGN/MELG/SKUE came from the owner file; my sb2live-only ISIN fixes
   were not touched in the repo and should not be merged over those.
