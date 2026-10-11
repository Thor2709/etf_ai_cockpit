import builtins
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.core.config import ModelRuntimeConfig
from etf_cockpit.models.toto_adapter import TotoAdapter, toto_quantiles_to_log_return_results
from etf_cockpit.application.forecast_service import _shadow_forecast, _forecast_to_row


def checkpoint(tmp_path):
    (tmp_path / 'config.json').write_text('{"patch_size":32}')
    (tmp_path / 'model.safetensors').write_bytes(b'fixture')
    return ModelRuntimeConfig(enabled=True, mode='live', backend='toto2', model_path=str(tmp_path), device='auto')


def prices():
    days = pd.bdate_range('2025-01-01', periods=100)
    return pd.DataFrame({'date': days, 'etf_id': 'ETF', 'adjusted_close': np.exp(np.arange(100) * .001)})


def test_toto2_local_loading_mask_and_shadow(monkeypatch, tmp_path):
    import torch
    calls = {}
    class Model:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls.update(path=path, **kwargs)
            return Model()
        def to(self, device):
            calls['device'] = str(device)
            return self
        def eval(self):
            return self
        def forecast(self, inputs, horizon, **kwargs):
            calls['inputs'] = inputs
            calls['forecast_kwargs'] = kwargs
            return torch.full((9, 1, 2, horizon), .001)
    original = builtins.__import__
    monkeypatch.setattr(builtins, '__import__', lambda name, *a, **kw: SimpleNamespace(Toto2Model=Model) if name == 'toto2' else original(name, *a, **kw))
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
    frame = prices()
    peer = frame.assign(etf_id='PEER')
    peer.loc[20, 'adjusted_close'] = np.nan
    frame = pd.concat([frame, peer], ignore_index=True)
    adapter = TotoAdapter(checkpoint(tmp_path))
    day = frame.date.iloc[70].date()
    row = adapter.forecast_etf('ETF', day, [5], prices=frame)[0]
    assert row.status == 'ok' and row.expected_return == pytest.approx(.005)
    assert calls['local_files_only'] is True and calls['device'] == 'cpu'
    assert str(calls['map_location']) == 'cpu'
    assert calls['inputs']['target'].shape == (1, 2, 64)
    assert (~calls['inputs']['target_mask']).any()
    assert calls['forecast_kwargs']['has_missing_values'] is True
    stored = _forecast_to_row(_shadow_forecast(row))
    assert stored['model_allowed_in_score'] is False
    assert stored['promotion_evidence_allowed'] is False
    assert stored['contamination_status'] == 'possibly_leaked'
    assert stored['execution_allowed'] is False


def test_toto2_history_is_per_instrument_and_point_in_time(tmp_path):
    adapter = TotoAdapter(checkpoint(tmp_path))
    frame = prices()
    sparse = frame.assign(etf_id='SPARSE', adjusted_close=np.nan)
    sparse.loc[60:, 'adjusted_close'] = frame.loc[60:, 'adjusted_close']
    frame = pd.concat([frame, sparse], ignore_index=True)
    day = date(2025, 3, 1)
    with pytest.raises(ValueError, match='SPARSE: no finite'):
        adapter.build_multivariate_input('SPARSE', day, frame)
    with pytest.raises(ValueError, match='found 7'):
        adapter.build_multivariate_input('SPARSE', prices().date.iloc[67].date(), frame)
    context = adapter.build_multivariate_input('ETF', day, frame).series
    assert max(context.index) <= day and np.isfinite(context['ETF']).all()


def test_toto2_missing_package_or_weights_and_toto1_are_unavailable(monkeypatch, tmp_path):
    config = checkpoint(tmp_path)
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == 'toto2':
            raise ImportError('absent')
        if name == 'toto.model.toto':
            return SimpleNamespace(Toto=object)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', importing)
    row = TotoAdapter(config).forecast_etf('ETF', date(2025, 1, 1), [5])[0]
    assert row.status == 'unavailable' and 'Toto 1 architecture' in row.reason_unavailable
    (tmp_path / 'model.safetensors').unlink()
    row = TotoAdapter(config).forecast_etf('ETF', date(2025, 1, 1), [5])[0]
    assert row.status == 'unavailable' and 'checkpoint missing or incomplete' in row.reason_unavailable
    assert row.expected_return is None and not row.model_allowed_in_score


def test_toto2_nonfinite_forecasts_never_become_returns():
    quantiles = np.zeros((9, 1, 1, 5))
    quantiles[4, 0, 0, 0] = np.nan
    with pytest.raises(ValueError, match='nonfinite'):
        toto_quantiles_to_log_return_results(quantiles=quantiles, horizons=[5], etf_id='ETF', forecast_date=date(2025, 1, 1), run_id='test', model_version='toto2')


def test_toto2_loader_errors_do_not_retry_without_local_only(monkeypatch, tmp_path):
    calls = []
    class Loader:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls.append(kwargs)
            raise TypeError('invalid checkpoint config')
    original = builtins.__import__
    monkeypatch.setattr(builtins, '__import__', lambda name, *a, **kw: SimpleNamespace(Toto2Model=Loader) if name == 'toto2' else original(name, *a, **kw))
    row = TotoAdapter(checkpoint(tmp_path)).forecast_etf('ETF', date(2025, 1, 1), [5], prices=prices())[0]
    assert row.status == 'failed' and row.expected_return is None
    assert len(calls) == 1 and calls[0]['local_files_only'] is True
