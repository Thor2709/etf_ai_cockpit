# Score lineage (#941)

One versioned lineage per visible score field (Blueprint Part 3 S3-01, S3-02, T3-01; Methods S10, S18).
The generated table is `score_lineage_manifest()` in `application/scoreboard_publication.py`; the check is
`tests/test_score_lineage.py` (it fails on any visible score field without a lineage row).

## Manifest columns

`field`, `surface` (`ui` / `export` / `scoreboard` / `history` / `api`), `origin_formula`, `code_path`,
`formula_version`, `weights_source`, `active_weights`, `config_hash`, `data_cutoff`, `eligibility_rule`,
`authority` (`descriptive` / `rank` / `decision`), `horizon`, `domain`, `rank_weight`. A visible score field is any
name ending in `_10` or one of `rank`, `score_rank`, `score`, `coverage`, `final_score_10`.

## Three score paths, declared

| Path | Code | Authority | Notes |
|---|---|---|---|
| Legacy composite (`final_combined_score_10`, API `score`, `research_score_10`) | `signals/simple_scores.py` | `rank` while the cutover is off (it produces the visible rank today); `descriptive` once DA-v1 is active | Forecast weight 0 (owner rule F5). The only number stored as "the score". |
| v3 canonical groups (`canonical_*_10`) | `configs/score_engine_v3.yaml`, `signals/canonical_scoring.py` | `descriptive` | 1-3 month view; the file's own `expected_return` weights size the separate forecast domain only. |
| Decision Architecture v1 with the QV / QVM benchmark rankers (`decision` surface: `active_rank_score`, `v3_replay_score`, `benchmark_rankers.score`, `baseline_z`, percentiles, ranks) | `analysis/decision/*` | `decision` rows; becomes the visible rank only behind the #811 cutover gate | `resolve_rank_cutover` decides; missing config or record keeps the legacy rank. `score_rank_authority()` names the active path and the manifest derives its `rank` rows from it. |

Display annotations (`display_adjusted_score_10`, the missing-data penalty) are `descriptive` and never stored. UI `final_score_10` is the *displayed* value (the research score, or the display-adjusted value while the preference is on); the stored/exported/API value is `final_combined_score_10` / `score`, shown beside it as `research_score_10`. UI `rank` is the visible ordinal; `rank` in history/API is the stored research rank.

## Rules

1. **Displayed score is the ranked score.** With the missing-data penalty on, the visible rank is recomputed from the
   displayed value (`score_views._ranked_by_displayed_score`). The penalty is applied after publication: scoreboard,
   history, export and API read `published_scores()` (never penalised). Rank deltas use one basis:
   `score_views.displayed_rank_info` recomputes the previous rank from the previous run's stored score and coverage
   with the same penalty.
2. **Forecasts are a separate `expected_return` domain.** `canonical_scoring.rank_domain_weights()` returns 0.0 for it
   unless a promotion record has `promoted: true`, the paired `test_id` (#928) and a finite weight in (0, 1].
   `score_engine_v3.yaml` changes only with a `formula_version` bump (NS1: 3.0.0 -> 3.1.0 when the yaml became the single weight source; the pinned checksum moved with it). A comment edit would change `formula_checksum` (pinned in
   `tests/test_decision_domains.py` and stamped into history), so the "not a rank weight" statement lives here and in
   `canonical_scoring.py`.
3. **History is append-only.** A formula version bump adds rows with the new `formula_version`/`formula_checksum`;
   earlier rows are not rewritten. v3, QV/QVM and DA-v1 stay side by side; the live cutover is the explicit
   `cutover_active` flag.
4. **Evidence order.** "Latest" and run deltas order by `data_as_of_date`, then `run_completed_at`
   (`score_views.evidence_ordered_history`): a late backfill never becomes Latest.
5. **One signal per instrument.** The latest `signal_date` wins; same-date signals that disagree make the instrument
   unavailable (`latest_signal_per_instrument`). Conflicting duplicate scores in one run are not persisted.
6. **Typed API.** `ScoreViewModel.score` is the 0-10 research score (the raw signal in [-1, 1] is never exposed under
   that name); score-only instruments are included; instruments without a canonical row have `score = None`.
7. **Instrument detail.** The headline is the live canonical row. A stored scoreboard row whose
   `source_vintage_hash` / `formula_checksum` differs (or cannot be verified) is replaced by the live row's evidence.
8. **Price freshness.** A score history row is `ok` only if its price row is dated, finite and positive, not after the
   run and not older than 10 days; component labels cannot override that.
