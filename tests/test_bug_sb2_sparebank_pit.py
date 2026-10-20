"""Native regression guards for issue 970; synthetic evidence only."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis.sparebank import analyse_sparebank_ec, load_sparebank_scorecard_policy
from etf_cockpit.analysis.sparebank.bank_economics import build_bank_economics, capital_resilience
from etf_cockpit.analysis.sparebank.scorecard import _input_source, _input_value, build_sparebank_scorecard
from etf_cockpit.application import sparebank_evidence as evidence, sparebank_peers as peers
from etf_cockpit.data import score_history
from etf_cockpit.signals import simple_scores


def _analysis(bank=None, metrics=()):
    claim = json.loads((Path(__file__).parent / 'fixtures/sparebank/teaching_bank.json').read_text())
    return analyse_sparebank_ec(claim, decision_time='2025-04-01T00:00:00Z', bank_economics_evidence=bank or {}, bank_metrics=metrics)


def _input(card, name):
    return next(row for axis in card.axes.values() for row in axis['inputs'] if row['id'] == name)


def test_b118_n001_percent_fallback_keeps_lcr_gate():
    analysis = _analysis(metrics=({'metric': 'liquidity_coverage_ratio', 'value': 90, 'unit': 'percent', 'source_id': 'fixture:lcr'},))
    assert analysis.bank_economics.funding['lcr'] == pytest.approx(.9)
    # Gates must remain visible even when a sparse scorecard has no composite.
    assert 'LCR_BELOW_MINIMUM' in analysis.scorecard.gate_reasons


def test_b118_n002_no_cross_vintage_funding_merge():
    old = {'funding': {'lcr': .9, 'provenance': {'lcr': {'period': '2024-12-31', 'source_locator': 'old'}}}}
    new = {'funding': {'nsfr': 1.1, 'provenance': {'nsfr': {'period': '2025-03-31', 'source_locator': 'new'}}}}
    result = evidence.merge_bank_economics_evidence(old, None, new)
    assert result['funding'].get('lcr') is None
    assert result['funding']['nsfr'] == 1.1


def test_b118_n003_reciprocal_deposit_ratio():
    bank = build_bank_economics(bank_metrics=[{'metric': 'loan_deposit_ratio', 'value': 2, 'unit': 'ratio', 'source_id': 'fixture:loans'}])
    assert bank.funding['deposit_to_loan_ratio'] == .5


def test_b119_n001_cet1_scope_must_match():
    bank = build_bank_economics({'cet1_ratio': .17, 'cet1_requirement_ratio': .139,
        'cet1_ratio_provenance': {'scope': 'group', 'period': '2024-12-31', 'source_locator': 'group'},
        'cet1_requirement_provenance': {'scope': 'parent', 'period': '2024-12-31', 'source_locator': 'parent'}})
    assert bank.resilience.get('headroom_pp') is None
    assert bank.reasons.get('cet1_headroom_pp')


@pytest.mark.parametrize('rwa', [0, -1])
def test_b119_n003_nonpositive_rwa_unavailable(rwa):
    result = capital_resilience(100, 5, 1, rwa, .1)
    assert result.status == 'unavailable'
    assert result.closing_ratio is None
    assert result.headroom_nok is None


def test_b119_n002_unextracted_rwa_stays_unavailable(tmp_path, monkeypatch):
    from etf_cockpit.data.pillar3_extract import extract_figures
    figures = extract_figures(['31.12.2024\nRisk-weighted assets 1,000 NOK'])
    monkeypatch.setattr(evidence, 'load_queue', lambda *_: {'figures': figures})
    assert evidence.pillar3_evidence(tmp_path, 'X', '2025-04-01', target_period='2024-12-31').get('rwa_nok') is None


def test_b023_n001_numeric_evidence_requires_provenance():
    card = _analysis({'funding': {'lcr': 1.5}}).scorecard
    row = _input(card, 'lcr_pct')
    assert row['rating_10'] is None
    assert row['reason']


def test_b023_n002_no_unrelated_metric_provenance():
    context = {'bank_economics': {'funding': {'lcr': 1.5, 'provenance': {'nsfr': {'source_locator': 'only NSFR'}}}}}
    assert _input_source({'source': 'bank_economics.funding.lcr'}, context) is None


def test_b023_n003_conditional_caps_apply_only_when_condition_present():
    policy = load_sparebank_scorecard_policy()
    policy = replace(policy, hard_gates={**policy.hard_gates, 'unresolved_claim': 0})
    from test_sparebank_scorecard import _complete_scorecard
    card = build_sparebank_scorecard(_complete_scorecard(), decision_time='2025-04-01', decision_price=100, valuation_assumptions={'assumption_source': 'fixture:valuation', 'central_owner_value_per_ec': 130, 'cost_of_equity': .05, 'marketability': {'days_to_trade': 21}}, policy=policy)
    assert card.composite_before_gate_cap_10 is not None
    assert 'OWNER_CLAIM_UNRESOLVED' not in card.gate_reasons


def _history(tmp_path, rows):
    policy = load_sparebank_scorecard_policy()
    path = tmp_path / 'data/derived/score_history.parquet'
    path.parent.mkdir(parents=True)
    pd.DataFrame([{'instrument_id': 'X', 'run_id': 'sparebank:X:' + when,
        'run_started_at': when, 'run_completed_at': when, 'known_at': when,
        'formula_version': policy.formula_version, 'formula_checksum': checksum or policy.formula_checksum,
        'final_combined_score_10': value} for when, value, checksum in rows]).to_parquet(path)


def test_b024_n001_history_applies_decision_cutoff(tmp_path):
    _history(tmp_path, [('2025-01-01T00:00:00Z', 4, None), ('2025-06-01T00:00:00Z', 9, None)])
    rows = score_history.latest_sparebank_scores(root=tmp_path, decision_time='2025-04-01T00:00:00Z')
    assert rows['X']['final_combined_score_10'] == 4


def test_a024_n001_native_selection_forwards_cutoff(monkeypatch):
    received = []
    monkeypatch.setattr(simple_scores, 'latest_sparebank_scores', lambda **kwargs: received.append(kwargs) or {})
    simple_scores._native_sparebank_score('X', decision_time='2025-04-01T00:00:00Z')
    assert received == [{'decision_time': '2025-04-01T00:00:00Z'}]


def test_b024_n003_history_checks_formula_checksum(tmp_path):
    _history(tmp_path, [('2025-01-01T00:00:00Z', 4, 'wrong')])
    assert score_history.latest_sparebank_scores(root=tmp_path) == {}


def test_e101_n001_raw_score_cannot_replace_native(monkeypatch):
    monkeypatch.setattr(simple_scores, 'latest_sparebank_scores', lambda **_: {})
    score = simple_scores._sparebank_scorecard_status(instrument_key='X', display_id='X', name='X', yahoo_symbol='X', asset_type='equity_certificate', instrument_currency='NOK', isin=None, data_policy='local')
    assert simple_scores._as_sparebank_pending(replace(score, final_score_10=99)).final_score_10 is None


def test_c115_n003_screener_does_not_pair_tactical_forecast(monkeypatch):
    from etf_cockpit.application import screening_data
    instrument = SimpleNamespace(id='X', name='X', instrument_type='equity_certificate', asset_class='equity', region=None, sector=None, theme=None, analysis_tier='sparebanken')
    snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=[instrument])), signals=[SimpleNamespace(etf_id='X', confidence=.9, supporting_metrics={'canonical_expected_return_10': 8})])
    monkeypatch.setattr(screening_data, '_canonical_scores', lambda _: {'X': SimpleNamespace(final_score_10=4)})
    row = screening_data.build_screen_rows(snapshot, pd.DataFrame()).iloc[0]
    assert pd.isna(row['expected_return']) and pd.isna(row['confidence'])


def test_e003_n002_peer_history_retains_earlier_snapshot(tmp_path):
    for when, score in [('2025-01-01', 4), ('2025-06-01', 9)]:
        peers.record_peer_row(tmp_path, {'instrument_id': 'X', 'as_of': when, 'composite': score})
    rows = peers.load_peer_rows(tmp_path, 'SELF', '2025-04-01')
    assert len(rows) == 1 and rows[0]['composite'] == 4


def test_e003_n003_zero_score_orders_before_missing(tmp_path):
    for name, score in [('A', None), ('Z', 0)]:
        peers.record_peer_row(tmp_path, {'instrument_id': name, 'as_of': '2025-01-01', 'composite': score})
    assert [r['instrument_id'] for r in peers.load_peer_rows(tmp_path, 'SELF')] == ['Z', 'A']


def test_e03_c2_n001_cached_projection_cannot_leak_future(tmp_path, monkeypatch):
    from etf_cockpit.application import financial_institution_views as views
    monkeypatch.setattr(views, 'verify_financial_projection', lambda x: x)
    projection = {'instrument_id': 'X', 'status': 'available', 'decision_time': '2025-06-01T00:00:00Z'}
    result = views.load_financial_institution_projection('X', projection=projection, decision_time='2025-01-01T00:00:00Z', storage_root=tmp_path)
    assert result['status'] == 'unavailable'


def test_e03_c2_n002_queue_status_is_as_of(tmp_path):
    from etf_cockpit.data import pillar3_queue
    pillar3_queue.save_queue(tmp_path, 'X', {'documents': [], 'figures': [{'metric': 'lcr_pct', 'value': 90, 'status': 'confirmed', 'extracted_at': '2025-01-01T00:00:00Z', 'decided_at': '2025-06-01T00:00:00Z'}]})
    queue = pillar3_queue.load_queue(tmp_path, 'X', decision_time='2025-04-01T00:00:00Z')
    assert queue['figures'][0]['status'] == 'pending'
    assert not queue['figures'][0].get('decided_at')


def test_e03_c2_n003_rwa_display_is_nok(monkeypatch):
    from etf_cockpit.app.pages import _sparebank_view as view
    import flet as ft
    captured = []
    monkeypatch.setattr(view, 'DataTable', lambda columns, rows, **kwargs: captured.extend(rows) or ft.Container())
    view._pillar3({'pillar3': {'figures': [{'metric': 'rwa_nok', 'value': 1000, 'status': 'confirmed'}]}}, None, None, 'X')
    assert captured[0]['value'] == '1,000 NOK'


def test_e03_c2_n004_decision_price_uses_currency(monkeypatch):
    from etf_cockpit.app.pages import _sparebank_view as view
    import flet as ft
    tiles = []
    monkeypatch.setattr(view, 'KpiTile', lambda *args, **kwargs: tiles.append(args) or ft.Container())
    view._valuation({'decision_price': {'price': 10, 'currency': 'EUR'}})
    assert any(row[0] == 'Price (decision)' and row[1] == '10.00 EUR' for row in tiles)


def test_b_c4_s23_n001_conflicting_assumptions_unavailable():
    rule = {'source': 'bank_economics.normalised.normalised_roe', 'transform': 'normalised_roe_spread_percentage_points'}
    context = {'bank_economics': {'normalised': {'normalised_roe': .15}}, 'assumptions': {'cost_of_equity': .10, 'cost_of_equity_pct': 5}}
    assert _input_value(rule, context) is None


def test_same_vintage_funding_and_metric_provenance_positive_control():
    old = {'funding': {'lcr': .9, 'provenance': {'lcr': {'period': '2024-12-31', 'source_locator': 'fixture:lcr'}}}}
    new = {'funding': {'nsfr': 1.1, 'provenance': {'nsfr': {'period': '2024-12-31', 'source_locator': 'fixture:nsfr'}}}}
    merged = evidence.merge_bank_economics_evidence(old, None, new)
    card = _analysis(merged).scorecard
    assert _input(card, 'lcr_pct')['rating_10'] is not None
    assert _input(card, 'lcr_pct')['source_locator'] == 'fixture:lcr'
    assert _input(card, 'nsfr_pct')['value'] == pytest.approx(110)


def test_matching_cet1_scope_and_period_positive_control():
    source = {'scope': 'group', 'period': '2024-12-31', 'source_locator': 'fixture:capital'}
    bank = build_bank_economics({'cet1_ratio': .17, 'cet1_requirement_ratio': .15, 'cet1_ratio_provenance': source, 'cet1_requirement_provenance': source})
    assert bank.resilience['headroom_pp'] == pytest.approx(2)
    assert _input_source({'source': 'bank_economics.resilience'}, {'bank_economics': bank})


@pytest.mark.parametrize('missing', ['scope', 'period'])
def test_cet1_unverifiable_pair_withholds_headroom(missing):
    source = {'scope': 'group', 'period': '2024-12-31', 'source_locator': 'fixture:capital'}
    del source[missing]
    bank = build_bank_economics({'cet1_ratio': .17, 'cet1_requirement_ratio': .15, 'cet1_ratio_provenance': source, 'cet1_requirement_provenance': source})
    assert bank.resilience.get('headroom_pp') is None


def test_matching_assumption_aliases_positive_control():
    rule = {'source': 'bank_economics.normalised.normalised_roe', 'transform': 'normalised_roe_spread_percentage_points'}
    assert _input_value(rule, {'bank_economics': {'normalised': {'normalised_roe': .15}}, 'assumptions': {'cost_of_equity': .1, 'cost_of_equity_pct': 10}}) == pytest.approx(5)


def test_history_and_peers_invalid_cutoff_fail_closed(tmp_path):
    _history(tmp_path, [('2025-01-01T00:00:00Z', 4, None)])
    assert score_history.latest_sparebank_scores(root=tmp_path, decision_time='invalid') == {}
    peers.record_peer_row(tmp_path, {'instrument_id': 'X', 'as_of': '2025-01-01', 'composite': 4})
    assert peers.load_peer_rows(tmp_path, 'SELF', 'invalid') == []


def test_history_missing_timing_or_checksum_is_unavailable(tmp_path):
    _history(tmp_path, [('2025-01-01T00:00:00Z', 4, None)])
    path = tmp_path / 'data/derived/score_history.parquet'
    pd.read_parquet(path).drop(columns=['run_completed_at']).to_parquet(path)
    assert score_history.latest_sparebank_scores(root=tmp_path, decision_time='2025-04-01') == {}


def test_candidate_score_selection_forwards_replay_date(monkeypatch):
    from datetime import date
    received = []
    monkeypatch.setattr(simple_scores, 'latest_sparebank_scores', lambda **kwargs: received.append(kwargs) or {})
    rows = pd.DataFrame([{'instrument_id': 'X', 'asset_type': 'equity_certificate', 'latest_date': '2025-06-01'}])
    result = simple_scores.build_candidate_simple_scores(rows, None, decision_date=date(2025, 4, 1))
    assert len(result) == 1 and result[0].final_score_10 is None
    assert received == [{'decision_time': date(2025, 4, 1)}]


def test_instrument_detail_forwards_snapshot_cutoff(monkeypatch):
    from etf_cockpit.application import instrument_detail_view as view
    from etf_cockpit.application.snapshot_builder import build_snapshot
    snapshot = build_snapshot()
    received = []
    class ProjectionReached(Exception):
        pass
    def capture(*args, **kwargs):
        received.append(kwargs['decision_time'])
        raise ProjectionReached
    monkeypatch.setattr(view, 'load_financial_institution_projection', capture)
    with pytest.raises(ProjectionReached):
        view.build_instrument_detail(snapshot, snapshot.config.universe.enabled_ids[0])
    assert pd.Timestamp(received[0]) == pd.Timestamp(snapshot.data_report.as_of_date).tz_localize('UTC')
