"""Local, deterministic portfolio optimiser contracts.

The optimiser is deliberately dependency-light.  It consumes returns built
from adjusted prices, keeps cash outside the invested weights, and never
creates a broker instruction.  Numerical methods are bounded and every
solution carries feasibility, fallback and binding-constraint evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

OPTIMISER_MODEL_VERSION = "portfolio-optimiser.v1"
METHODS = (
    "equal_weight",
    "inverse_volatility",
    "minimum_variance",
    "equal_risk_contribution",
    "hrp",
    "maximum_diversification",
    "cvar",
    "robust_mean_risk",
)


@dataclass(frozen=True)
class OptimiserConstraints:
    """Long-only constraints for invested weights.

    ``cash_weight`` is fixed and therefore invested weights sum to its
    complement.  Group labels can represent sector, country, currency or a
    caller-defined factor bucket.  A group cap is advisory unless supplied.
    """

    cash_weight: float = 0.0
    min_weight: float = 0.0
    max_weight: float = 1.0
    turnover_limit: float | None = None
    group_labels: Mapping[str, str] | None = None
    group_max_weights: Mapping[str, float] | None = None


@dataclass(frozen=True)
class OptimiserSolution:
    method: str
    weights: pd.Series
    status: str
    feasible: bool
    objective: float | None
    diagnostics: Mapping[str, object]
    warnings: tuple[str, ...] = ()
    model_version: str = OPTIMISER_MODEL_VERSION
    execution_allowed: bool = False

    @property
    def weight_sum(self) -> float:
        return float(self.weights.sum())


def returns_from_adjusted_prices(prices: pd.DataFrame, *, window: int = 252) -> pd.DataFrame:
    """Build a clean return matrix from explicitly adjusted prices.

    Raw close is never substituted.  A missing adjusted-price column is a
    visible unavailable state rather than a silent change in methodology.
    """

    required = {"date", "etf_id", "adjusted_close"}
    if prices is None or prices.empty or not required.issubset(prices.columns):
        return pd.DataFrame()
    frame = prices[["date", "etf_id", "adjusted_close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.dropna(subset=["date", "etf_id", "adjusted_close"])
    frame = frame[frame["adjusted_close"] > 0]
    if frame.empty:
        return pd.DataFrame()
    pivot = frame.pivot_table(index="date", columns="etf_id", values="adjusted_close", aggfunc="last").sort_index()
    result = pivot.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna(how="all")
    return result.tail(int(window)) if window > 0 else result


class PortfolioOptimiser:
    """Solve transparent local portfolio candidates with bounded fallbacks."""

    def __init__(self, returns: pd.DataFrame, *, seed: int = 42) -> None:
        self.returns = _clean_returns(returns)
        self.seed = int(seed)
        self.ids = list(self.returns.columns)
        self.covariance = _covariance(self.returns)
        self.expected_returns = self.returns.mean() * 252.0 if not self.returns.empty else pd.Series(dtype=float)

    def solve(
        self,
        method: str,
        *,
        constraints: OptimiserConstraints | None = None,
        current_weights: Mapping[str, float] | pd.Series | None = None,
        expected_returns: Mapping[str, float] | pd.Series | None = None,
    ) -> OptimiserSolution:
        requested = str(method).strip().lower()
        constraints = constraints or OptimiserConstraints()
        current_for_fallback: pd.Series | None = None
        try:
            _validate_constraints(constraints)
            self._validate_inputs()
            if requested not in METHODS:
                raise ValueError(f"unsupported optimiser method: {requested}")
            current = _normalise_series(current_weights, self.ids, default=0.0)
            current_for_fallback = current
            expected = _normalise_series(expected_returns, self.ids, default=None)
            weights = self._solve_method(requested, constraints, current, expected)
            weights = _project_weights(weights, constraints, self.ids, current)
            diagnostics = _diagnostics(weights, self.covariance, constraints, current)
            return OptimiserSolution(
                requested,
                weights,
                "success",
                bool(diagnostics["feasible"]),
                _objective(requested, weights, self.returns, self.covariance, expected),
                diagnostics,
                tuple(diagnostics["warnings"]),
            )
        except (FloatingPointError, KeyError, TypeError, ValueError, np.linalg.LinAlgError) as exc:
            # A numerical failure must be visible.  A feasible equal-weight
            # candidate is safer than arbitrary solver output and is marked as
            # a fallback so it cannot be mistaken for the requested method.
            try:
                fallback = _project_weights(_equal_weights(self.ids, constraints), constraints, self.ids, current_for_fallback)
            except (TypeError, ValueError) as fallback_exc:
                return OptimiserSolution(
                    requested,
                    pd.Series(dtype=float),
                    "unavailable",
                    False,
                    None,
                    {"feasible": False, "warnings": [f"solver_failure:{exc}", f"fallback_unavailable:{fallback_exc}"]},
                    (f"solver_failure:{exc}", f"fallback_unavailable:{fallback_exc}"),
                )
            diagnostics = _diagnostics(fallback, self.covariance, constraints, None)
            warning = f"solver_failure:{type(exc).__name__}:{exc}"
            warnings = tuple([warning, "visible_equal_weight_fallback", *diagnostics["warnings"]])
            return OptimiserSolution(
                requested,
                fallback,
                "fallback",
                bool(diagnostics["feasible"]),
                _objective("equal_weight", fallback, self.returns, self.covariance, None),
                {**diagnostics, "fallback_method": "equal_weight"},
                warnings,
            )

    def compare(
        self,
        methods: Iterable[str] = METHODS,
        *,
        constraints: OptimiserConstraints | None = None,
        current_weights: Mapping[str, float] | pd.Series | None = None,
    ) -> pd.DataFrame:
        """Compare candidates on a held-out tail while retaining equal weight."""

        names = list(dict.fromkeys(["equal_weight", *(str(item) for item in methods)]))
        split = max(1, int(len(self.returns) * 0.7))
        validation = self.returns.iloc[split:]
        rows: list[dict[str, object]] = []
        for name in names:
            solution = self.solve(name, constraints=constraints, current_weights=current_weights)
            portfolio = validation.reindex(columns=self.ids).fillna(0.0) @ solution.weights.reindex(self.ids).fillna(0.0)
            rows.append(
                {
                    "method": name,
                    "status": solution.status,
                    "feasible": solution.feasible,
                    "weight_sum": solution.weight_sum,
                    "validation_observations": int(len(portfolio)),
                    "validation_return_ann": float(portfolio.mean() * 252.0) if len(portfolio) else None,
                    "validation_vol_ann": float(portfolio.std(ddof=1) * math.sqrt(252.0)) if len(portfolio) > 1 else None,
                    "max_weight": float(solution.weights.max()) if not solution.weights.empty else None,
                    "binding_constraints": ",".join(solution.diagnostics.get("binding_constraints", ())),
                    "warnings": ";".join(solution.warnings),
                    "fingerprint": optimiser_fingerprint(solution),
                }
            )
        return pd.DataFrame(rows)

    def sensitivity(self, method: str, *, constraints: OptimiserConstraints | None = None, shock: float = 0.05) -> dict[str, object]:
        """Report deterministic weight movement under a return perturbation."""

        if not math.isfinite(float(shock)) or not 0 <= float(shock) <= 1:
            raise ValueError("shock must be between 0 and 1")
        base = self.solve(method, constraints=constraints)
        shocked_returns = self.returns.copy()
        if not shocked_returns.empty:
            shocked_returns.iloc[:, 0] = shocked_returns.iloc[:, 0] * (1.0 + float(shock))
        shocked = PortfolioOptimiser(shocked_returns, seed=self.seed).solve(method, constraints=constraints)
        movement = shocked.weights.reindex(self.ids).fillna(0.0) - base.weights.reindex(self.ids).fillna(0.0)
        return {
            "method": str(method),
            "shock": float(shock),
            "base_status": base.status,
            "shocked_status": shocked.status,
            "max_abs_weight_change": float(movement.abs().max()) if not movement.empty else 0.0,
            "weight_change": {str(key): float(value) for key, value in movement.items()},
        }

    def _validate_inputs(self) -> None:
        if len(self.ids) < 1 or self.returns.empty:
            raise ValueError("at least one adjusted-price return series is required")
        if not np.isfinite(self.returns.to_numpy(float)).all():
            raise ValueError("returns contain non-finite values")

    def _solve_method(self, method: str, constraints: OptimiserConstraints, current: pd.Series, expected: pd.Series) -> pd.Series:
        if method == "equal_weight":
            return _equal_weights(self.ids, constraints)
        if method == "inverse_volatility":
            volatility = self.returns.std(ddof=1).replace(0.0, np.nan).fillna(np.inf)
            return _normalise_positive(1.0 / volatility, self.ids, constraints)
        if method == "minimum_variance":
            return _project_weights(_minimum_variance(self.covariance), constraints, self.ids, current)
        if method == "equal_risk_contribution":
            return _equal_risk_contribution(self.covariance, constraints, self.ids)
        if method == "hrp":
            return _hrp(self.covariance, constraints, self.ids)
        if method == "maximum_diversification":
            return _maximum_diversification(self.covariance, constraints, self.ids)
        if method == "cvar":
            return _cvar(self.returns, constraints, self.ids)
        if method == "robust_mean_risk":
            means = expected if not expected.empty else self.expected_returns
            return _robust_mean_risk(means, self.covariance, constraints, self.ids)
        raise ValueError(f"unsupported optimiser method: {method}")


def _clean_returns(returns: pd.DataFrame) -> pd.DataFrame:
    if returns is None or returns.empty:
        return pd.DataFrame()
    frame = returns.copy()
    frame.columns = [str(column) for column in frame.columns]
    frame = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna(how="any")
    return frame.loc[:, ~frame.columns.duplicated()].sort_index()


def _covariance(returns: pd.DataFrame) -> pd.DataFrame:
    if returns.empty:
        return pd.DataFrame()
    matrix = returns.cov().fillna(0.0) * 252.0
    values = matrix.to_numpy(float)
    values = (values + values.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(values)
    floor = max(float(np.max(np.diag(values))) * 1e-10, 1e-12)
    repaired = eigenvectors @ np.diag(np.maximum(eigenvalues, floor)) @ eigenvectors.T
    return pd.DataFrame(repaired, index=matrix.index, columns=matrix.columns)


def _validate_constraints(constraints: OptimiserConstraints) -> None:
    values = (constraints.cash_weight, constraints.min_weight, constraints.max_weight)
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError("cash and weight constraints must be finite")
    if not 0 <= constraints.cash_weight < 1:
        raise ValueError("cash_weight must be between 0 and 100% exclusive")
    if not 0 <= constraints.min_weight <= constraints.max_weight <= 1:
        raise ValueError("weight bounds must satisfy 0 <= min <= max <= 1")
    if constraints.turnover_limit is not None and not 0 <= float(constraints.turnover_limit) <= 2:
        raise ValueError("turnover_limit must be between 0 and 2")
    for group, limit in (constraints.group_max_weights or {}).items():
        if not 0 < float(limit) <= 1:
            raise ValueError(f"group limit for {group} must be between 0 and 100%")


def _normalise_series(values: Mapping[str, float] | pd.Series | None, ids: list[str], default: float | None) -> pd.Series:
    if values is None:
        if default is None:
            return pd.Series(dtype=float)
        return pd.Series(float(default), index=ids, dtype=float)
    frame = pd.Series(values, dtype=float).reindex(ids).fillna(0.0)
    if not np.isfinite(frame.to_numpy(float)).all():
        raise ValueError("weights or expected returns contain non-finite values")
    return frame


def _equal_weights(ids: list[str], constraints: OptimiserConstraints) -> pd.Series:
    invested = 1.0 - float(constraints.cash_weight)
    if not ids or invested < len(ids) * constraints.min_weight - 1e-9 or invested > len(ids) * constraints.max_weight + 1e-9:
        raise ValueError("weight bounds cannot satisfy the invested total")
    return pd.Series(invested / len(ids), index=ids, dtype=float)


def _normalise_positive(values: pd.Series, ids: list[str], constraints: OptimiserConstraints) -> pd.Series:
    values = values.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    if float(values.sum()) <= 0:
        return _equal_weights(ids, constraints)
    return _project_weights(values / float(values.sum()) * (1.0 - constraints.cash_weight), constraints, ids, None)


def _minimum_variance(covariance: pd.DataFrame) -> pd.Series:
    ids = list(covariance.index)
    inverse = np.linalg.pinv(covariance.to_numpy(float))
    ones = np.ones(len(ids))
    weights = inverse @ ones
    denominator = float(ones @ weights)
    if denominator <= 0 or not np.isfinite(denominator):
        raise np.linalg.LinAlgError("minimum-variance system has no stable positive solution")
    return pd.Series(weights / denominator, index=ids)


def _equal_risk_contribution(covariance: pd.DataFrame, constraints: OptimiserConstraints, ids: list[str]) -> pd.Series:
    weights = np.ones(len(ids), dtype=float) / len(ids)
    matrix = covariance.reindex(index=ids, columns=ids).to_numpy(float)
    for _ in range(500):
        marginal = matrix @ weights
        risk = weights * marginal
        target = max(float(risk.sum()), 1e-12) / len(ids)
        updated = weights * np.sqrt(target / np.maximum(risk, 1e-12))
        updated = updated / max(float(updated.sum()), 1e-12)
        if float(np.max(np.abs(updated - weights))) < 1e-10:
            break
        weights = 0.5 * weights + 0.5 * updated
    return _project_weights(pd.Series(weights * (1.0 - constraints.cash_weight), index=ids), constraints, ids, None)


def _hrp(covariance: pd.DataFrame, constraints: OptimiserConstraints, ids: list[str]) -> pd.Series:
    matrix = covariance.reindex(index=ids, columns=ids).to_numpy(float)
    volatility = np.sqrt(np.maximum(np.diag(matrix), 1e-12))
    correlation = matrix / np.outer(volatility, volatility)
    # A deterministic nearest-neighbour order is a small, dependency-free
    # substitute for hierarchical clustering and is auditable in diagnostics.
    remaining = list(range(len(ids)))
    order = [remaining.pop(0)]
    while remaining:
        last = order[-1]
        chosen = min(remaining, key=lambda index: (1.0 - correlation[last, index], ids[index]))
        remaining.remove(chosen)
        order.append(chosen)
    weights = np.ones(len(ids), dtype=float)
    clusters = [order]
    while clusters:
        next_clusters: list[list[int]] = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            midpoint = len(cluster) // 2
            left, right = cluster[:midpoint], cluster[midpoint:]
            left_var = _cluster_variance(matrix, left)
            right_var = _cluster_variance(matrix, right)
            left_share = right_var / max(left_var + right_var, 1e-12)
            weights[right] *= 1.0 - left_share
            weights[left] *= left_share
            next_clusters.extend((left, right))
        clusters = next_clusters
    return _project_weights(pd.Series(weights * (1.0 - constraints.cash_weight), index=ids), constraints, ids, None)


def _cluster_variance(matrix: np.ndarray, cluster: list[int]) -> float:
    values = np.ones(len(cluster), dtype=float) / len(cluster)
    subset = matrix[np.ix_(cluster, cluster)]
    return max(float(values @ subset @ values), 1e-12)


def _maximum_diversification(covariance: pd.DataFrame, constraints: OptimiserConstraints, ids: list[str]) -> pd.Series:
    volatility = pd.Series(np.sqrt(np.maximum(np.diag(covariance.reindex(index=ids, columns=ids).to_numpy(float)), 1e-12)), index=ids)
    weights = _normalise_positive(volatility, ids, constraints)
    matrix = covariance.reindex(index=ids, columns=ids).to_numpy(float)
    vector = weights.to_numpy(float)
    for _ in range(200):
        portfolio_vol = max(float(np.sqrt(vector @ matrix @ vector)), 1e-12)
        numerator = volatility.to_numpy(float) / portfolio_vol - (float(vector @ volatility.to_numpy(float)) / portfolio_vol**3) * (matrix @ vector)
        vector = _project_array(vector + 0.02 * numerator, constraints, None, ids)
    return pd.Series(vector, index=ids)


def _cvar(returns: pd.DataFrame, constraints: OptimiserConstraints, ids: list[str]) -> pd.Series:
    matrix = returns.reindex(columns=ids).to_numpy(float)
    if len(matrix) < 5:
        return _equal_weights(ids, constraints)
    weights = _equal_weights(ids, constraints).to_numpy(float)
    for _ in range(150):
        portfolio = matrix @ weights
        threshold = float(np.quantile(portfolio, 0.05))
        tail = matrix[portfolio <= threshold]
        if len(tail) == 0:
            break
        gradient = -tail.mean(axis=0)
        weights = _project_array(weights - 0.05 * gradient, constraints, None, ids)
    return pd.Series(weights, index=ids)


def _robust_mean_risk(means: pd.Series, covariance: pd.DataFrame, constraints: OptimiserConstraints, ids: list[str]) -> pd.Series:
    expected = means.reindex(ids).fillna(0.0).to_numpy(float)
    matrix = covariance.reindex(index=ids, columns=ids).to_numpy(float)
    # Conservative uncertainty penalty prevents fragile high-mean allocations.
    uncertainty = np.sqrt(np.maximum(np.diag(matrix), 1e-12)) * 0.5
    score = expected - uncertainty
    inverse = np.linalg.pinv(matrix)
    vector = inverse @ score
    if not np.isfinite(vector).all() or vector.sum() <= 0:
        return _equal_weights(ids, constraints)
    return _project_weights(pd.Series(vector, index=ids), constraints, ids, None)


def _project_weights(values: pd.Series, constraints: OptimiserConstraints, ids: list[str], current: pd.Series | None) -> pd.Series:
    vector = _project_array(values.reindex(ids).fillna(0.0).to_numpy(float), constraints, current, ids)
    return pd.Series(vector, index=ids, dtype=float)


def _project_array(values: np.ndarray, constraints: OptimiserConstraints, current: pd.Series | None, ids: list[str]) -> np.ndarray:
    if len(values) != len(ids):
        raise ValueError("weight vector does not match the instrument universe")
    invested = 1.0 - constraints.cash_weight
    values = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    values = np.clip(values, constraints.min_weight, constraints.max_weight)
    for _ in range(100):
        difference = invested - float(values.sum())
        if abs(difference) < 1e-10:
            break
        if difference > 0:
            eligible = values < constraints.max_weight - 1e-12
            if not np.any(eligible):
                raise ValueError("maximum weights cannot reach the invested total")
            values[eligible] += difference / int(eligible.sum())
        else:
            eligible = values > constraints.min_weight + 1e-12
            if not np.any(eligible):
                raise ValueError("minimum weights cannot reach the invested total")
            values[eligible] += difference / int(eligible.sum())
        values = np.clip(values, constraints.min_weight, constraints.max_weight)
    if constraints.turnover_limit is not None and current is not None:
        baseline = current.reindex(ids).fillna(0.0).to_numpy(float)
        baseline = _project_array(baseline, OptimiserConstraints(cash_weight=constraints.cash_weight, min_weight=0.0, max_weight=constraints.max_weight), None, ids)
        turnover = float(np.abs(values - baseline).sum())
        if turnover > float(constraints.turnover_limit) + 1e-9:
            fraction = float(constraints.turnover_limit) / max(turnover, 1e-12)
            values = baseline + fraction * (values - baseline)
    labels = constraints.group_labels or {}
    for group, limit in (constraints.group_max_weights or {}).items():
        members = np.array([labels.get(identifier) == group for identifier in ids], dtype=bool)
        total = float(values[members].sum())
        if total > float(limit) + 1e-9 and total > 0:
            values[members] *= float(limit) / total
            remainder = invested - float(values.sum())
            outside = ~members & (values < constraints.max_weight - 1e-12)
            if remainder > 0 and np.any(outside):
                values[outside] += remainder / int(outside.sum())
    values = np.clip(values, constraints.min_weight, constraints.max_weight)
    for group, limit in (constraints.group_max_weights or {}).items():
        members = np.array([labels.get(identifier) == group for identifier in ids], dtype=bool)
        if float(values[members].sum()) > float(limit) + 1e-7:
            raise ValueError(f"group constraint remains infeasible for {group}")
    if constraints.turnover_limit is not None and current is not None:
        turnover = float(np.abs(values - current.reindex(ids).fillna(0.0).to_numpy(float)).sum())
        if turnover > float(constraints.turnover_limit) + 1e-7:
            raise ValueError("turnover constraint remains infeasible")
    if not math.isclose(float(values.sum()), invested, abs_tol=1e-6):
        raise ValueError("projected weights do not reconcile to the invested total")
    return values


def _diagnostics(weights: pd.Series, covariance: pd.DataFrame, constraints: OptimiserConstraints, current: pd.Series | None) -> dict[str, object]:
    values = weights.to_numpy(float)
    invested = 1.0 - constraints.cash_weight
    warnings: list[str] = []
    binding: list[str] = []
    if abs(float(values.sum()) - invested) > 1e-6:
        warnings.append("weight_reconciliation_failed")
    if any(abs(value - constraints.min_weight) <= 1e-7 for value in values):
        binding.append("min_weight")
    if any(abs(value - constraints.max_weight) <= 1e-7 for value in values):
        binding.append("max_weight")
    turnover = None
    if current is not None:
        turnover = float(np.abs(values - current.reindex(weights.index).fillna(0.0).to_numpy(float)).sum())
        if constraints.turnover_limit is not None and turnover >= float(constraints.turnover_limit) - 1e-6:
            binding.append("turnover_limit")
    for group, limit in (constraints.group_max_weights or {}).items():
        group_total = sum(float(weight) for identifier, weight in weights.items() if (constraints.group_labels or {}).get(identifier) == group)
        if group_total >= float(limit) - 1e-6:
            binding.append(f"group:{group}")
    feasible = bool(
        math.isclose(float(values.sum()), invested, abs_tol=1e-6)
        and np.isfinite(values).all()
        and (values >= constraints.min_weight - 1e-7).all()
        and (values <= constraints.max_weight + 1e-7).all()
    )
    return {"feasible": feasible, "weight_sum": float(values.sum()), "invested_weight": invested, "turnover": turnover, "binding_constraints": tuple(dict.fromkeys(binding)), "warnings": tuple(warnings)}


def _objective(method: str, weights: pd.Series, returns: pd.DataFrame, covariance: pd.DataFrame, expected: pd.Series) -> float | None:
    if weights.empty:
        return None
    vector = weights.reindex(covariance.index).fillna(0.0).to_numpy(float)
    if method in {"minimum_variance", "equal_risk_contribution", "hrp", "maximum_diversification", "cvar", "inverse_volatility", "equal_weight"}:
        return float(max(0.0, vector @ covariance.to_numpy(float) @ vector))
    mean = (expected if not expected.empty else returns.mean() * 252.0).reindex(covariance.index).fillna(0.0).to_numpy(float)
    return float(vector @ mean - 0.5 * (vector @ covariance.to_numpy(float) @ vector))


def optimiser_fingerprint(solution: OptimiserSolution) -> str:
    """Return a stable audit fingerprint for solver/method/weights."""

    payload = f"{solution.model_version}|{solution.method}|{solution.status}|" + ",".join(f"{key}:{value:.12f}" for key, value in solution.weights.items())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "METHODS",
    "OPTIMISER_MODEL_VERSION",
    "OptimiserConstraints",
    "OptimiserSolution",
    "PortfolioOptimiser",
    "optimiser_fingerprint",
    "returns_from_adjusted_prices",
]
