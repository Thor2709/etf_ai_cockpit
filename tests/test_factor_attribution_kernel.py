"""Factor attribution of rank validation vs its former pandas form (the oracles of base 52d46f27): exact equality."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from etf_cockpit.analysis.decision import rank_validation as rv
from etf_cockpit.portfolio import factor_risk as fr


def _oracle_attribution(
    rows: pd.DataFrame,
    ranker: str,
    prices: pd.DataFrame,
    policy: rv.RankValidationPolicy,
) -> dict[str, object]:
    required = {"instrument_id", "date", "known_at", "adjusted_close"}
    if not rv._has_columns(prices, required):
        return {"status": "unavailable", "reason": "factor risk requires point-in-time adjusted-price history", "factors": []}
    contributions: list[dict[str, object]] = []
    stamped: pd.DataFrame | None = None
    for decision_time, group in rows.loc[rows["ranker"].astype(str).eq(ranker)].groupby("decision_time", sort=True):
        cutoff = rv._aware_timestamp(decision_time)
        if cutoff is None:
            continue
        valid = group.loc[group["score"].map(rv._finite)].sort_values(
            ["score", "instrument_id"], ascending=[False, True], kind="stable"
        )
        selected = valid.head(min(policy.top_n, len(valid)))
        if len(selected) < 3:
            continue
        if stamped is None:  # the stamps do not depend on the decision time: parse them once
            stamped = prices[["instrument_id", "date", "known_at", "adjusted_close"]].copy()
            stamped["_known"] = rv._map_repeated(stamped["known_at"], rv._aware_timestamp)
            stamped["_date"] = rv._map_repeated(stamped["date"], rv._date_value)
        price_rows = stamped.loc[
            stamped["_known"].notna()
            & stamped["_known"].le(cutoff)
            & stamped["_date"].map(lambda value: value is not None and value <= cutoff.date())
            & stamped["instrument_id"].astype(str).isin(valid["instrument_id"].astype(str)),
            ["instrument_id", "date", "adjusted_close"],
        ]
        prices_for_risk = price_rows.rename(columns={"instrument_id": "etf_id"})
        allocation = pd.DataFrame(
            {
                "etf_id": selected["instrument_id"].astype(str),
                "current_weight": 1.0 / len(selected),
                "market_value_eur": selected["size_value"].map(rv._float_or_none).fillna(1.0)
                if "size_value" in selected
                else 1.0,
            }
        )
        features = pd.DataFrame(
            {
                "etf_id": valid["instrument_id"].astype(str),
                "date": pd.Timestamp(cutoff.date()),
                "quality_score_10": valid["quality_score"],
                "value_score_10": valid["value_score"],
                "momentum_120d": valid["momentum_score"],
            }
        )
        try:
            report = rv.build_factor_risk_report(
                prices_for_risk,
                allocation,
                latest_features=features,
                window=252,
            )
        except (ArithmeticError, KeyError, TypeError, ValueError):
            continue
        portfolio = report.get("portfolio_contributions")
        if not isinstance(portfolio, pd.DataFrame) or portfolio.empty:
            continue
        for row in portfolio.to_dict("records"):
            factor = str(row.get("factor", ""))
            if factor in {"quality", "value", "momentum"}:
                contributions.append(
                    {
                        "decision_time": str(decision_time),
                        "factor": factor,
                        "variance_contribution": rv._float_or_none(row.get("variance_contribution")),
                        "variance_share": rv._float_or_none(row.get("variance_share")),
                        "factor_model_version": report.get("model_version"),
                    }
                )
    factors = {item["factor"] for item in contributions}
    status = "available" if {"quality", "value", "momentum"}.issubset(factors) else "unavailable"
    return {
        "status": status,
        "method": "portfolio.factor_risk Q/V/M variance attribution",
        "factors": contributions,
        "reason": None if status == "available" else "Q/V/M factor-risk contributions were not all estimable",
    }


def _oracle_fit(returns: pd.DataFrame, exposures: pd.DataFrame, panels: list[tuple[pd.Timestamp, pd.DataFrame]] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    factor_names = list(exposures.columns)
    factor_rows: list[dict[str, object]] = []
    residual_rows: list[dict[str, object]] = []
    dates = sorted(returns.index)
    usable_dates = 0
    for dt in dates:
        matrix = exposures
        if panels is not None:
            known = [item for day, item in panels if day < pd.Timestamp(dt).normalize()]
            if not known:
                continue
            matrix = known[-1]
        joined = pd.concat([returns.loc[[dt]].T.rename(columns={dt: "observed_return"}), matrix], axis=1, join="inner")
        joined = joined.dropna(subset=["observed_return", *factor_names])
        minimum = max(5, 2 * len(factor_names))
        if len(joined) < minimum:
            continue
        beta, standard_error, residual = fr._robust_fit(joined[factor_names].to_numpy(float), joined["observed_return"].to_numpy(float))
        usable_dates += 1
        for index, factor in enumerate(factor_names):
            factor_rows.append({"date": pd.Timestamp(dt).date(), "factor": factor, "factor_return": float(beta[index]), "standard_error": float(standard_error[index]), "sample_count": int(len(joined)), "method": "robust_cross_sectional"})
        fitted = joined[factor_names].to_numpy(float) @ beta
        for instrument_id, observed, fitted_value, residual_value in zip(joined.index, joined["observed_return"], fitted, residual):
            residual_rows.append({"date": pd.Timestamp(dt).date(), "instrument_id": str(instrument_id), "observed_return": float(observed), "fitted_return": float(fitted_value), "residual": float(residual_value)})
    factor_columns = ["date", "factor", "factor_return", "standard_error", "sample_count", "method"]
    residual_columns = ["date", "instrument_id", "observed_return", "fitted_return", "residual"]
    return pd.DataFrame(factor_rows, columns=factor_columns), pd.DataFrame(residual_rows, columns=residual_columns), {"candidate_dates": len(dates), "usable_dates": usable_dates, "factor_count": len(factor_names)}


def _oracle_specific_risk(residuals: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    ids = sorted(map(str, returns.columns))
    rows: list[dict[str, object]] = []
    for instrument_id in ids:
        values = residuals.loc[residuals["instrument_id"].eq(instrument_id), "residual"] if not residuals.empty else pd.Series(dtype=float)
        values = pd.to_numeric(values, errors="coerce").dropna()
        volatility = float(values.std(ddof=1) * np.sqrt(fr.ANNUALISATION_FACTOR)) if len(values) >= 2 else float("nan")
        rows.append({"instrument_id": instrument_id, "specific_vol_ann": volatility, "sample_count": int(len(values)), "coverage": float(len(values) / max(1, len(returns)))})
    return pd.DataFrame(rows)


def _prices(names: int = 14, sessions: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    days = pd.bdate_range("2023-01-02", periods=sessions)
    rows = []
    for item in range(names):
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01 * (1 + item / 4), sessions)))
        for index, day in enumerate(days):
            lag = 3 if index % 17 == item else 0  # some rows become known days later
            rows.append({"instrument_id": f"I{item}", "date": day.date().isoformat(), "adjusted_close": close[index],
                         "known_at": (day + pd.Timedelta(days=lag, hours=18)).isoformat() + "Z"})
    frame = pd.DataFrame(rows)
    frame.loc[5, "adjusted_close"] = 0.0
    frame.loc[6, "adjusted_close"] = np.nan
    frame.loc[7, "known_at"] = "not-a-timestamp"
    late = frame.iloc[[40, 41]].assign(adjusted_close=[1.5, 2.5])  # a later duplicate (date, instrument) row wins
    return pd.concat([frame, late]).sample(frac=1.0, random_state=3).reset_index(drop=True)


def _rows(prices: pd.DataFrame, names: int = 14) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    days = sorted(prices["date"].unique())
    decisions = [f"{day}T23:00:00Z" for day in (days[5], days[150], days[260], days[-1])]
    return pd.DataFrame(
        [
            {"decision_time": decision, "ranker": "r", "instrument_id": f"I{item}", "score": float(rng.normal()),
             "quality_score": float(rng.normal()), "value_score": float(rng.normal()),
             "momentum_score": float(rng.normal()), "size_value": float(rng.uniform(1, 9))}
            for decision in decisions
            for item in range(names)
        ]
    )


def _assert_same(left: object, right: object) -> None:
    if isinstance(left, pd.DataFrame) and isinstance(right, pd.DataFrame):
        if left.empty and right.empty:
            assert list(left.columns) == list(right.columns) or left.columns.empty or right.columns.empty
            return
        pd.testing.assert_frame_equal(left, right, check_exact=True)
    elif isinstance(left, dict):
        assert isinstance(right, dict) and left.keys() == right.keys()
        for key in left:
            _assert_same(left[key], right[key])
    elif isinstance(left, float) and np.isnan(left):
        assert isinstance(right, float) and np.isnan(right)
    else:
        assert type(left) is type(right) and left == right


def test_log_returns_match_the_pandas_return_matrix() -> None:
    prices = _prices()
    arrays = rv.ReplayInputs(pd.DataFrame(), prices, pd.DataFrame()).factor_prices()
    stamped = prices.assign(_known=prices["known_at"].map(rv._aware_timestamp), _date=prices["date"].map(rv._date_value))
    for day in ("2023-01-03", "2023-03-15", "2023-12-29", "2024-02-20"):
        cutoff = pd.Timestamp(f"{day}T23:00:00Z")
        for ids in ({"I0", "I1", "I2"}, {f"I{item}" for item in range(14)}, {"I99"}):
            frame = stamped.loc[
                stamped["_known"].notna() & stamped["_known"].le(cutoff)
                & stamped["_date"].map(lambda value: value is not None and value <= cutoff.date())
                & stamped["instrument_id"].astype(str).isin(ids)
            ].rename(columns={"instrument_id": "etf_id"})
            for window in (252, 5, 0):
                expected = fr._return_matrix(frame, window=window)
                actual = arrays.log_returns(cutoff, ids, window)
                if expected.empty:
                    assert actual.empty
                else:
                    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_fit_and_specific_risk_match_the_oracles() -> None:
    prices = _prices()
    returns = rv.ReplayInputs(pd.DataFrame(), prices, pd.DataFrame()).factor_prices().log_returns(
        pd.Timestamp("2024-02-20T23:00:00Z"), {f"I{item}" for item in range(14)}, 252
    )
    rng = np.random.default_rng(5)
    exposures = pd.DataFrame(rng.normal(size=(9, 2)), index=[f"I{item}" for item in (7, 0, 1, 2, 3, 4, 5, 6, 99)], columns=["a", "b"])
    exposures.iloc[2, 1] = np.nan
    panels = [(pd.Timestamp("2023-06-01"), exposures), (pd.Timestamp("2023-09-01"), exposures.iloc[::-1] * 2.0)]
    # C- and Fortran-ordered blocks, with and without rows that drop
    for panel, exposures in ((None, exposures), (panels, exposures), ([], exposures), (None, exposures.fillna(0.0)), (None, exposures.T.copy().T)):
        expected = _oracle_fit(returns, exposures, panel)
        actual = fr._fit_cross_sectional(returns, exposures, panel)
        assert actual[2] == expected[2]
        pd.testing.assert_frame_equal(actual[0], expected[0], check_exact=True)
        pd.testing.assert_frame_equal(actual[1], expected[1], check_exact=True)
        pd.testing.assert_frame_equal(fr._specific_risk(actual[1], returns), _oracle_specific_risk(expected[1], returns), check_exact=True)


def test_factor_attribution_matches_the_oracle(monkeypatch) -> None:
    prices = _prices()
    rows = _rows(prices)
    reports: list[dict[str, object]] = []
    original = rv.build_factor_risk_report

    def recording(*args: object, **kwargs: object) -> dict[str, object]:
        reports.append(original(*args, **kwargs))
        return reports[-1]

    monkeypatch.setattr(rv, "build_factor_risk_report", recording)
    statuses = []
    for top_n in (14, 5):  # all valid ids selected (attribution available) and a top-n subset
        policy = replace(rv.load_rank_validation_policy(), top_n=top_n)
        reports.clear()
        actual = rv._factor_attribution(rows, "r", rv.ReplayInputs(pd.DataFrame(), prices, pd.DataFrame()), policy)
        new_reports = list(reports)
        with monkeypatch.context() as patch:
            patch.setattr(fr, "_fit_cross_sectional", _oracle_fit)
            patch.setattr(fr, "_specific_risk", _oracle_specific_risk)
            reports.clear()
            expected = _oracle_attribution(rows, "r", prices, policy)
        assert actual == expected
        statuses.append(actual["status"])
        assert len(new_reports) == len(reports) == 4
        for new, old in zip(new_reports, reports):
            new["coverage"].pop("price_observations"), old["coverage"].pop("price_observations")
            _assert_same(new, old)
    assert statuses == ["available", "unavailable"]
