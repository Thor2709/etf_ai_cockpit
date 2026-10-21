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

from etf_cockpit.portfolio.robust_risk import ledoit_wolf_covariance

OPTIMISER_MODEL_VERSION = "portfolio-optimiser.v2"
METHODS = (
    "equal_weight",
    "inverse_volatility",
    "minimum_variance",
    "equal_risk_contribution",
    "hrp_like",
    "maximum_diversification",
    "cvar",
    "robust_mean_risk",
)
# ``hrp`` was a heuristic (nearest-neighbour ordering + recursive bisection), not
# canonical hierarchical risk parity.  The old id stays accepted but is reported.
METHOD_ALIASES = {"hrp": "hrp_like"}
ANNUALISATION = 252.0
# Conservative documented defaults (open parameters of #947).
MIN_COVARIANCE_OBSERVATIONS = 20  # fewer shared rows: covariance status is insufficient_sample
RETURN_SHRINKAGE_PRIOR_OBSERVATIONS = 252  # mean shrunk toward zero by n / (n + prior)
CVAR_ALPHA = 0.05
MIN_CVAR_TAIL_OBSERVATIONS = 5
ROBUST_ESTIMATION_ERROR_Z = 0.5  # penalty = z x standard error of the annual mean (the mean is already shrunk toward zero)
COVARIANCE_SHRINKAGE_MODES = ("ledoit_wolf", "none")
DEFAULT_COST_BPS = 10.0


class _MethodUnavailable(ValueError):
    """A method cannot be solved from the evidence; never replaced by equal weight."""

    def __init__(self, reason_code: str, message: str, details: Mapping[str, object] | None = None) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code
        self.details = dict(details or {})


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

    def __init__(self, returns: pd.DataFrame, *, seed: int = 42, covariance_shrinkage: str = "ledoit_wolf") -> None:
        if covariance_shrinkage not in COVARIANCE_SHRINKAGE_MODES:
            raise ValueError(f"covariance_shrinkage must be one of {COVARIANCE_SHRINKAGE_MODES}")
        self.covariance_shrinkage = covariance_shrinkage
        self.input_issues: list[str] = []
        self.returns = _clean_returns(returns, self.input_issues)
        self.seed = int(seed)
        self.ids = list(self.returns.columns)
        # Annual units throughout: mean = daily mean x 252 and covariance = daily covariance x 252,
        # estimated on the supplied (training) window only.
        self.covariance, self.covariance_diagnostics = _covariance(self.returns, covariance_shrinkage)
        self.historical_mean_annual = self.returns.mean() * ANNUALISATION if not self.returns.empty else pd.Series(dtype=float)
        # A historical mean is not an expected alpha: it is shrunk toward the zero active baseline.
        # Promoted Part 3 forecasts (#811) enter only through the explicit ``expected_returns`` argument.
        self.return_shrinkage_factor = _return_shrinkage_factor(len(self.returns))
        self.expected_returns = self.historical_mean_annual * self.return_shrinkage_factor
        self.expected_return_basis = "historical_mean_shrunk_toward_zero_baseline"

    def solve(
        self,
        method: str,
        *,
        constraints: OptimiserConstraints | None = None,
        current_weights: Mapping[str, float] | pd.Series | None = None,
        expected_returns: Mapping[str, float] | pd.Series | None = None,
    ) -> OptimiserSolution:
        requested = str(method).strip().lower()
        alias_warnings: tuple[str, ...] = ()
        if requested in METHOD_ALIASES:
            alias_warnings = (f"deprecated_method_alias:{requested}->{METHOD_ALIASES[requested]}",)
            requested = METHOD_ALIASES[requested]
        constraints = constraints or OptimiserConstraints()
        current_for_fallback: pd.Series | None = None
        try:
            _validate_constraints(constraints)
        except (TypeError, ValueError) as exc:
            warning = f"invalid_constraints:{exc}"
            return OptimiserSolution(
                requested,
                pd.Series(dtype=float),
                "unavailable",
                False,
                None,
                {"feasible": False, "reason_code": "invalid_constraints", "warnings": [warning]},
                (warning,),
            )
        try:
            self._validate_inputs()
            if requested not in METHODS:
                raise ValueError(f"unsupported optimiser method: {requested}")
            current = _normalise_series(current_weights, self.ids, default=0.0)
            current_for_fallback = current
            if requested == "robust_mean_risk" and expected_returns is not None:
                try:
                    expected = pd.Series(expected_returns, dtype=float).reindex(self.ids)
                except (TypeError, ValueError) as exc:
                    raise ValueError("expected_returns_unavailable: expected means must be numeric") from exc
                if expected.isna().any() or not np.isfinite(expected.to_numpy(float)).all():
                    raise ValueError("expected_returns_unavailable: missing_expected_returns")
            else:
                expected = _normalise_series(expected_returns, self.ids, default=None)
            weights = self._solve_method(requested, constraints, current, expected)
            weights = _project_weights(weights, constraints, self.ids, current)
            diagnostics = _diagnostics(weights, self.covariance, constraints, current)
            diagnostics.update(self._method_context(requested))
            objective, objective_name = _objective(requested, weights, self.returns, self.covariance, expected, self.expected_returns)
            diagnostics["objective_name"] = objective_name
            return OptimiserSolution(
                requested,
                weights,
                "success",
                bool(diagnostics["feasible"]),
                objective,
                diagnostics,
                (*alias_warnings, *diagnostics["warnings"]),
            )
        except _MethodUnavailable as exc:
            return OptimiserSolution(
                requested,
                pd.Series(dtype=float),
                "unavailable",
                False,
                None,
                {"feasible": False, "reason_code": exc.reason_code, "warnings": [str(exc)], **exc.details},
                (*alias_warnings, str(exc)),
            )
        except (FloatingPointError, KeyError, TypeError, ValueError, np.linalg.LinAlgError) as exc:
            if str(exc).startswith(("covariance_unavailable:", "expected_returns_unavailable:")):
                reason_code = str(exc).split(":", 1)[0]
                reason_detail = str(exc).split(":", 1)[1].strip()
                return OptimiserSolution(
                    requested,
                    pd.Series(dtype=float),
                    "unavailable",
                    False,
                    None,
                    {"feasible": False, "reason_code": reason_code, "reason_detail": reason_detail, "warnings": [str(exc)]},
                    (*alias_warnings, str(exc)),
                )
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
                _objective("equal_weight", fallback, self.returns, self.covariance, None, self.expected_returns)[0],
                {**diagnostics, "fallback_method": "equal_weight"},
                (*alias_warnings, *warnings),
            )

    def compare(
        self,
        methods: Iterable[str] = METHODS,
        *,
        constraints: OptimiserConstraints | None = None,
        current_weights: Mapping[str, float] | pd.Series | None = None,
        core_id: str | None = None,
        core_weight: float = 0.8,
        cost_bps: float = DEFAULT_COST_BPS,
        stability_repetitions: int = 8,
        stability_block_size: int = 10,
    ) -> pd.DataFrame:
        """Compare candidates on a held-out tail while retaining equal weight.

        Every row uses the same training head, validation tail and cost
        assumption (``cost_bps`` per unit of turnover versus ``current_weights``,
        charged once per year).  ``core_id`` adds the core-only and core + sleeve
        reference portfolios (e.g. VWCE).  ``weight_stability_*`` reports how far
        the weights move under date-block resampling of the training head.
        """

        names = list(dict.fromkeys(["equal_weight", *(METHOD_ALIASES.get(str(item).strip().lower(), str(item)) for item in methods)]))
        split = max(1, int(len(self.returns) * 0.7))
        validation = self.returns.iloc[split:]
        # Candidate weights are fitted on the training head only; the validation
        # tail must never influence the covariance/returns behind the weights.
        training = PortfolioOptimiser(self.returns.iloc[:split], seed=self.seed, covariance_shrinkage=self.covariance_shrinkage)
        effective = constraints or OptimiserConstraints()
        current = _normalise_series(current_weights, self.ids, default=0.0)
        candidates: list[tuple[str, OptimiserSolution]] = [(name, training.solve(name, constraints=constraints, current_weights=current_weights)) for name in names]
        if core_id is not None:
            candidates.extend(_reference_solutions(self.ids, str(core_id), float(core_weight), effective, training.covariance))
        rows: list[dict[str, object]] = []
        for name, solution in candidates:
            usable = solution.status in {"success", "fallback"} and not solution.weights.empty
            row: dict[str, object] = {
                "method": name,
                "status": solution.status,
                "feasible": solution.feasible,
                "weight_sum": solution.weight_sum if usable else None,
                "validation_observations": 0,
                "validation_return_ann": None,
                "validation_vol_ann": None,
                "turnover": None,
                "cost_bps": float(cost_bps),
                "validation_return_net_ann": None,
                "max_weight": float(solution.weights.max()) if usable else None,
                "binding_constraints": ",".join(solution.diagnostics.get("binding_constraints", ())),
                "reason_code": solution.diagnostics.get("reason_code"),
                "warnings": ";".join(solution.warnings),
                "fingerprint": optimiser_fingerprint(solution),
                "weight_stability_status": "unavailable",
                "weight_stability_mean_shift": None,
                "weight_stability_max_shift": None,
            }
            if usable:
                # An unavailable solver has no weights: its validation figures stay None, never 0.
                portfolio = validation.reindex(columns=self.ids).fillna(0.0) @ solution.weights.reindex(self.ids).fillna(0.0)
                row["validation_observations"] = int(len(portfolio))
                gross = float(portfolio.mean() * ANNUALISATION) if len(portfolio) else None
                row["validation_return_ann"] = gross
                row["validation_vol_ann"] = float(portfolio.std(ddof=1) * math.sqrt(ANNUALISATION)) if len(portfolio) > 1 else None
                turnover = float(np.abs(solution.weights.reindex(self.ids).fillna(0.0).to_numpy(float) - current.to_numpy(float)).sum())
                row["turnover"] = turnover
                if gross is not None:
                    row["validation_return_net_ann"] = gross - turnover * float(cost_bps) / 10_000.0
                if name in METHODS or name == "equal_weight":
                    stability = training.weight_stability(
                        name,
                        constraints=constraints,
                        current_weights=current_weights,
                        block_size=stability_block_size,
                        repetitions=stability_repetitions,
                    )
                    row["weight_stability_status"] = stability["status"]
                    row["weight_stability_mean_shift"] = stability.get("mean_weight_shift")
                    row["weight_stability_max_shift"] = stability.get("max_weight_shift")
            rows.append(row)
        return pd.DataFrame(rows)

    def weight_stability(
        self,
        method: str,
        *,
        constraints: OptimiserConstraints | None = None,
        current_weights: Mapping[str, float] | pd.Series | None = None,
        block_size: int = 10,
        repetitions: int = 20,
    ) -> dict[str, object]:
        """Weight movement under seeded date-block resampling of the fitting window.

        ``mean_weight_shift`` is the mean half-L1 distance (share of the book
        that would move) between the base and the resampled solutions.  Fewer
        than half successful resamples is ``unavailable``, never a zero shift.
        """

        base = self.solve(method, constraints=constraints, current_weights=current_weights)
        if base.status != "success":
            return {"status": "unavailable", "reason_code": base.diagnostics.get("reason_code", "base_solution_unavailable"), "method": base.method}
        count = int(repetitions)
        observations = len(self.returns)
        block = max(1, min(int(block_size), observations))
        if count < 2:
            return {"status": "unavailable", "reason_code": "stability_repetitions_below_two", "method": base.method}
        generator = np.random.default_rng(self.seed)
        blocks = int(math.ceil(observations / block))
        shifts: list[float] = []
        samples: list[np.ndarray] = []
        base_vector = base.weights.reindex(self.ids).to_numpy(float)
        for _ in range(count):
            starts = generator.integers(0, observations - block + 1, size=blocks)
            index = np.concatenate([np.arange(start, start + block) for start in starts])[:observations]
            resampled = PortfolioOptimiser(self.returns.iloc[index].reset_index(drop=True), seed=self.seed, covariance_shrinkage=self.covariance_shrinkage)
            solution = resampled.solve(method, constraints=constraints, current_weights=current_weights)
            if solution.status != "success":
                continue
            vector = solution.weights.reindex(self.ids).to_numpy(float)
            samples.append(vector)
            shifts.append(0.5 * float(np.abs(vector - base_vector).sum()))
        if len(shifts) < max(2, count // 2):
            return {"status": "unavailable", "reason_code": "insufficient_successful_resamples", "method": base.method, "successful_resamples": len(shifts), "repetitions": count}
        return {
            "status": "available",
            "method": base.method,
            "repetitions": count,
            "successful_resamples": len(shifts),
            "block_size": block,
            "mean_weight_shift": float(np.mean(shifts)),
            "max_weight_shift": float(np.max(shifts)),
            "asset_weight_std": {identifier: float(value) for identifier, value in zip(self.ids, np.std(np.vstack(samples), axis=0, ddof=0))},
        }

    def sensitivity(self, method: str, *, constraints: OptimiserConstraints | None = None, shock: float = 0.05) -> dict[str, object]:
        """Report deterministic weight movement under a return perturbation."""

        if not math.isfinite(float(shock)) or not 0 <= float(shock) <= 1:
            raise ValueError("shock must be between 0 and 1")
        base = self.solve(method, constraints=constraints)
        shocked_returns = self.returns.copy()
        if not shocked_returns.empty:
            shocked_returns.iloc[:, 0] = shocked_returns.iloc[:, 0] * (1.0 + float(shock))
        shocked = PortfolioOptimiser(shocked_returns, seed=self.seed, covariance_shrinkage=self.covariance_shrinkage).solve(method, constraints=constraints)
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
        if self.input_issues:
            # Distinct instruments that collapse to one identifier must never be silently dropped.
            raise ValueError(f"covariance_unavailable: {self.input_issues[0]}")
        if len(self.ids) < 1:
            raise ValueError("at least one adjusted-price return series is required")
        if self.returns.empty:
            raise ValueError("covariance_unavailable: no_shared_return_history")
        if len(self.returns) < 2:
            raise ValueError("covariance_unavailable: insufficient_shared_return_history")
        if len(self.returns) < MIN_COVARIANCE_OBSERVATIONS:
            raise ValueError(f"covariance_unavailable: insufficient_sample:{len(self.returns)}<{MIN_COVARIANCE_OBSERVATIONS}")
        if not np.isfinite(self.returns.to_numpy(float)).all():
            raise ValueError("returns contain non-finite values")
        if self.covariance.empty or not np.isfinite(self.covariance.to_numpy(float)).all():
            raise ValueError("covariance_unavailable: covariance_inputs_incomplete")

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
        if method == "hrp_like":
            return _hrp_like(self.covariance, constraints, self.ids)
        if method == "maximum_diversification":
            return _maximum_diversification(self.covariance, constraints, self.ids)
        if method == "cvar":
            return _cvar(self.returns, constraints, self.ids)
        if method == "robust_mean_risk":
            means = expected if not expected.empty else self.expected_returns
            return _robust_mean_risk(means, self.covariance, len(self.returns), constraints, self.ids)
        raise ValueError(f"unsupported optimiser method: {method}")

    def _method_context(self, method: str) -> dict[str, object]:
        context: dict[str, object] = {
            "covariance": dict(self.covariance_diagnostics),
            "observations": int(len(self.returns)),
            "expected_return_basis": self.expected_return_basis,
            "return_shrinkage_factor": self.return_shrinkage_factor,
        }
        if method == "cvar":
            context["tail_alpha"] = CVAR_ALPHA
            context["tail_observations"] = _cvar_tail_size(len(self.returns))
            context["minimum_tail_observations"] = MIN_CVAR_TAIL_OBSERVATIONS
        if method == "robust_mean_risk":
            context["penalty"] = "estimation_error_standard_error"
            context["estimation_error_z"] = ROBUST_ESTIMATION_ERROR_Z
        if method == "hrp_like":
            context["method_note"] = "heuristic: nearest-neighbour ordering and recursive bisection, not canonical hierarchical risk parity"
        return context


def _clean_returns(returns: pd.DataFrame, issues: list[str] | None = None) -> pd.DataFrame:
    if returns is None or returns.empty:
        return pd.DataFrame()
    frame = returns.copy()
    labels = [str(column) for column in frame.columns]
    duplicated = sorted({label for label in labels if labels.count(label) > 1})
    if duplicated and issues is not None:
        issues.append(f"duplicate_instrument_ids:{','.join(duplicated)}")
    frame.columns = labels
    frame = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna(how="any")
    return frame.loc[:, ~frame.columns.duplicated()].sort_index()


def _return_shrinkage_factor(observations: int) -> float:
    """Weight kept on the historical mean; the rest shrinks toward the zero active baseline."""

    count = max(int(observations), 0)
    return count / (count + RETURN_SHRINKAGE_PRIOR_OBSERVATIONS)


def _covariance(returns: pd.DataFrame, shrinkage: str = "ledoit_wolf") -> tuple[pd.DataFrame, dict[str, object]]:
    """Annual covariance of the supplied training window with PSD repair.

    ``ledoit_wolf`` shrinks toward a scaled identity; ``none`` is the plain
    sample covariance.  Fewer than ``MIN_COVARIANCE_OBSERVATIONS`` rows is an
    ``insufficient_sample`` status and no matrix.
    """

    if len(returns) < 2:
        return pd.DataFrame(), {"status": "unavailable", "reason_code": "insufficient_shared_return_history", "observations": int(len(returns))}
    if len(returns) < MIN_COVARIANCE_OBSERVATIONS:
        return pd.DataFrame(), {"status": "insufficient_sample", "reason_code": "insufficient_sample", "observations": int(len(returns)), "minimum_observations": MIN_COVARIANCE_OBSERVATIONS}
    if shrinkage == "ledoit_wolf":
        daily, details = ledoit_wolf_covariance(returns)
        intensity = float(details.get("shrinkage_intensity", 0.0)) if details.get("status") == "available" else None
    else:
        daily, intensity = returns.cov(), 0.0
    matrix = daily * ANNUALISATION if not daily.empty else daily
    if matrix.empty or matrix.isna().to_numpy().any() or not np.isfinite(matrix.to_numpy(float)).all():
        return pd.DataFrame(), {"status": "unavailable", "reason_code": "covariance_inputs_incomplete", "observations": int(len(returns))}
    values = matrix.to_numpy(float)
    values = (values + values.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(values)
    floor = max(float(np.max(np.diag(values))) * 1e-10, 1e-12)
    repaired_values = np.maximum(eigenvalues, floor)
    repaired = eigenvectors @ np.diag(repaired_values) @ eigenvectors.T
    repaired = (repaired + repaired.T) / 2.0
    diagnostics = {
        "status": "available",
        "estimator": shrinkage,
        "shrinkage_intensity": intensity,
        "observations": int(len(returns)),
        "annualisation": ANNUALISATION,
        "positive_semidefinite": bool(np.linalg.eigvalsh(repaired).min() >= -1e-10),
        "minimum_eigenvalue_before_repair": float(eigenvalues.min()),
        "minimum_eigenvalue": float(repaired_values.min()),
        "psd_repaired": bool(np.any(eigenvalues < floor)),
    }
    return pd.DataFrame(repaired, index=matrix.index, columns=matrix.columns), diagnostics


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


def _hrp_like(covariance: pd.DataFrame, constraints: OptimiserConstraints, ids: list[str]) -> pd.Series:
    matrix = covariance.reindex(index=ids, columns=ids).to_numpy(float)
    volatility = np.sqrt(np.maximum(np.diag(matrix), 1e-12))
    correlation = matrix / np.outer(volatility, volatility)
    # HRP-like, not canonical HRP: a deterministic nearest-neighbour order replaces
    # agglomerative linkage + quasi-diagonalisation, then recursive bisection by
    # cluster variance.  The result is labelled as a heuristic everywhere.
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


def _cvar_tail_size(observations: int, alpha: float = CVAR_ALPHA) -> int:
    return int(math.ceil(float(alpha) * int(observations) - 1e-12))


def _tail_mean(portfolio: np.ndarray, alpha: float = CVAR_ALPHA) -> float:
    size = max(_cvar_tail_size(len(portfolio), alpha), 1)
    return float(np.sort(portfolio)[:size].mean())


def _cvar(returns: pd.DataFrame, constraints: OptimiserConstraints, ids: list[str]) -> pd.Series:
    matrix = returns.reindex(columns=ids).to_numpy(float)
    tail_size = _cvar_tail_size(len(matrix))
    if tail_size < MIN_CVAR_TAIL_OBSERVATIONS:
        # No equal-weight stand-in: a CVaR from a handful of tail points is not a CVaR solution.
        raise _MethodUnavailable(
            "insufficient_tail_sample",
            f"cvar tail has {tail_size} observations at alpha {CVAR_ALPHA:.0%}; at least {MIN_CVAR_TAIL_OBSERVATIONS} required",
            {
                "sample_status": "insufficient",
                "tail_observations": tail_size,
                "minimum_tail_observations": MIN_CVAR_TAIL_OBSERVATIONS,
                "tail_alpha": CVAR_ALPHA,
                "observations": int(len(matrix)),
            },
        )
    weights = _equal_weights(ids, constraints).to_numpy(float)
    for _ in range(150):
        portfolio = matrix @ weights
        tail = matrix[np.argsort(portfolio, kind="stable")[:tail_size]]
        gradient = -tail.mean(axis=0)
        weights = _project_array(weights - 0.05 * gradient, constraints, None, ids)
    return pd.Series(weights, index=ids)


def _robust_mean_risk(means: pd.Series, covariance: pd.DataFrame, observations: int, constraints: OptimiserConstraints, ids: list[str]) -> pd.Series:
    expected_series = pd.to_numeric(means.reindex(ids), errors="coerce")
    if expected_series.isna().any() or not np.isfinite(expected_series.to_numpy(float)).all():
        raise ValueError("expected_returns_unavailable: missing_expected_returns")
    expected = expected_series.to_numpy(float)
    matrix = covariance.reindex(index=ids, columns=ids).to_numpy(float)
    # Explicit estimation-error term: z x standard error of the annual mean, with the
    # standard error taken from the sample length in years (sigma / sqrt(T_years)).
    years = max(int(observations), 1) / ANNUALISATION
    standard_error = np.sqrt(np.maximum(np.diag(matrix), 1e-12) / years)
    score = expected - ROBUST_ESTIMATION_ERROR_Z * standard_error
    if not (score > 0).any():
        raise _MethodUnavailable(
            "no_positive_robust_score",
            "no instrument has a positive mean after the estimation-error penalty; no equal-weight stand-in is produced",
            {"robust_scores": {identifier: float(value) for identifier, value in zip(ids, score)}},
        )
    vector = np.linalg.pinv(matrix) @ score
    vector = np.where(np.isfinite(vector), np.maximum(vector, 0.0), 0.0)
    if float(vector.sum()) <= 0:
        raise _MethodUnavailable("no_positive_robust_score", "mean-risk solution has no positive long-only weight")
    vector = vector / float(vector.sum()) * (1.0 - constraints.cash_weight)
    return _project_weights(pd.Series(vector, index=ids), constraints, ids, None)


def _project_weights(values: pd.Series, constraints: OptimiserConstraints, ids: list[str], current: pd.Series | None) -> pd.Series:
    vector = _project_array(values.reindex(ids).fillna(0.0).to_numpy(float), constraints, current, ids)
    return pd.Series(vector, index=ids, dtype=float)


def _group_masks(constraints: OptimiserConstraints, ids: list[str]) -> list[tuple[np.ndarray, float]]:
    labels = constraints.group_labels or {}
    masks: list[tuple[np.ndarray, float]] = []
    for group, limit in (constraints.group_max_weights or {}).items():
        members = np.array([labels.get(identifier) == group for identifier in ids], dtype=bool)
        if members.any():
            masks.append((members, float(limit)))
    return masks


def _project_feasible(values: np.ndarray, constraints: OptimiserConstraints, ids: list[str]) -> np.ndarray:
    """Project onto box + invested total + group caps in one fixed-point loop.

    Group caps and the total are enforced together (cap excess is taken from the
    weight above the minimum, the deficit is spread only over headroom that
    respects every cap), so the result does not depend on the order in which the
    constraints are applied and a feasible allocation is never rejected.
    """

    invested = 1.0 - constraints.cash_weight
    low, high = float(constraints.min_weight), float(constraints.max_weight)
    groups = _group_masks(constraints, ids)
    reachable = high * len(ids)
    for members, limit in groups:
        reachable -= max(0.0, high * int(members.sum()) - limit)
    if invested > reachable + 1e-9:
        raise ValueError("maximum weights and group caps cannot reach the invested total")
    if invested < low * len(ids) - 1e-9:
        raise ValueError("minimum weights cannot reach the invested total")
    for members, limit in groups:
        if low * int(members.sum()) > limit + 1e-9:
            raise ValueError("group cap is below the minimum weights of its members")
    weights = np.clip(values, low, high)
    for _ in range(1000):
        for members, limit in groups:
            total = float(weights[members].sum())
            if total > limit:
                reducible = weights[members] - low
                weights[members] -= reducible * min(1.0, (total - limit) / max(float(reducible.sum()), 1e-300))
        difference = invested - float(weights.sum())
        if abs(difference) < 1e-12:
            break
        if difference > 0:
            room = high - weights
            for members, limit in groups:
                spare = max(limit - float(weights[members].sum()), 0.0)
                available = float(room[members].sum())
                if available > spare:
                    room[members] *= spare / max(available, 1e-300)
            capacity = float(room.sum())
            if capacity <= 1e-15:
                raise ValueError("maximum weights cannot reach the invested total")
            weights += room * min(1.0, difference / capacity)
        else:
            room = weights - low
            capacity = float(room.sum())
            if capacity <= 1e-15:
                raise ValueError("minimum weights cannot reach the invested total")
            weights -= room * min(1.0, -difference / capacity)
        weights = np.clip(weights, low, high)
    return weights


def _project_array(values: np.ndarray, constraints: OptimiserConstraints, current: pd.Series | None, ids: list[str]) -> np.ndarray:
    if len(values) != len(ids):
        raise ValueError("weight vector does not match the instrument universe")
    invested = 1.0 - constraints.cash_weight
    values = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    weights = _project_feasible(values, constraints, ids)
    if constraints.turnover_limit is not None and current is not None:
        baseline = current.reindex(ids).fillna(0.0).to_numpy(float)
        relaxed = OptimiserConstraints(
            cash_weight=constraints.cash_weight,
            min_weight=0.0,
            max_weight=constraints.max_weight,
            group_labels=constraints.group_labels,
            group_max_weights=constraints.group_max_weights,
        )
        try:
            baseline = _project_feasible(baseline, relaxed, ids)
        except ValueError:
            baseline = _project_feasible(baseline, OptimiserConstraints(cash_weight=constraints.cash_weight, min_weight=0.0, max_weight=constraints.max_weight), ids)
        turnover = float(np.abs(weights - baseline).sum())
        if turnover > float(constraints.turnover_limit) + 1e-9:
            fraction = float(constraints.turnover_limit) / max(turnover, 1e-12)
            weights = baseline + fraction * (weights - baseline)
    for members, limit in _group_masks(constraints, ids):
        if float(weights[members].sum()) > limit + 1e-7:
            raise ValueError("group constraint remains infeasible")
    if constraints.turnover_limit is not None and current is not None:
        turnover = float(np.abs(weights - current.reindex(ids).fillna(0.0).to_numpy(float)).sum())
        if turnover > float(constraints.turnover_limit) + 1e-7:
            raise ValueError("turnover constraint remains infeasible")
    if not math.isclose(float(weights.sum()), invested, abs_tol=1e-6):
        raise ValueError("projected weights do not reconcile to the invested total")
    return weights


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


def _objective(
    method: str,
    weights: pd.Series,
    returns: pd.DataFrame,
    covariance: pd.DataFrame,
    expected: pd.Series | None,
    default_expected: pd.Series | None = None,
) -> tuple[float | None, str]:
    """Value of the method's own criterion and its name (variance only where it is the criterion)."""

    if weights.empty:
        return None, "unavailable"
    vector = weights.reindex(covariance.index).fillna(0.0).to_numpy(float)
    matrix = covariance.to_numpy(float)
    variance = float(max(0.0, vector @ matrix @ vector))
    if method == "cvar":
        portfolio = returns.reindex(columns=covariance.index).to_numpy(float) @ vector
        if _cvar_tail_size(len(portfolio)) < MIN_CVAR_TAIL_OBSERVATIONS:
            return None, "cvar_daily_loss_5pct"
        return float(-_tail_mean(portfolio)), "cvar_daily_loss_5pct"
    if method == "maximum_diversification":
        volatility = np.sqrt(np.maximum(np.diag(matrix), 0.0))
        denominator = math.sqrt(variance)
        if denominator <= 1e-12:
            return None, "diversification_ratio"
        return float(vector @ volatility / denominator), "diversification_ratio"
    if method in {"minimum_variance", "equal_risk_contribution", "hrp_like", "inverse_volatility", "equal_weight"}:
        return variance, "annual_variance"
    given = expected if expected is not None and not expected.empty else default_expected
    if given is None or given.empty:
        given = returns.mean() * ANNUALISATION
    mean_series = given.reindex(covariance.index)
    if mean_series.isna().any() or not np.isfinite(mean_series.to_numpy(float)).all():
        return None, "mean_risk_utility"
    return float(vector @ mean_series.to_numpy(float) - 0.5 * variance), "mean_risk_utility"


def _reference_solutions(ids: list[str], core_id: str, core_weight: float, constraints: OptimiserConstraints, covariance: pd.DataFrame) -> list[tuple[str, OptimiserSolution]]:
    """Core-only and core + equal-weight sleeve references on the same universe."""

    results: list[tuple[str, OptimiserSolution]] = []
    for name in ("core_only", "core_sleeve"):
        reason = None
        if core_id not in ids:
            reason = "core_instrument_not_in_universe"
        elif not 0.0 < core_weight <= 1.0:
            reason = "invalid_core_weight"
        elif name == "core_sleeve" and len(ids) < 2:
            reason = "core_sleeve_needs_two_instruments"
        if reason is not None:
            results.append((name, OptimiserSolution(name, pd.Series(dtype=float), "unavailable", False, None, {"feasible": False, "reason_code": reason, "warnings": [reason]}, (reason,))))
            continue
        invested = 1.0 - constraints.cash_weight
        weights = pd.Series(0.0, index=ids)
        if name == "core_only":
            weights[core_id] = invested
        else:
            weights[:] = invested * (1.0 - core_weight) / (len(ids) - 1)
            weights[core_id] = invested * core_weight
        diagnostics = _diagnostics(weights, covariance, constraints, None)
        # Reference portfolios are not optimised: a breach of the user constraints is reported, not repaired.
        labels = constraints.group_labels or {}
        breach = any(
            float(sum(weights[identifier] for identifier in ids if labels.get(identifier) == group)) > float(limit) + 1e-7
            for group, limit in (constraints.group_max_weights or {}).items()
        )
        feasible = bool(diagnostics["feasible"]) and not breach
        warnings = (*diagnostics["warnings"], *(("reference_portfolio_breaches_constraints",) if not feasible else ()))
        results.append((name, OptimiserSolution(name, weights, "success", feasible, None, {**diagnostics, "feasible": feasible, "reference_portfolio": True}, warnings)))
    return results


def optimiser_fingerprint(solution: OptimiserSolution) -> str:
    """Return a stable audit fingerprint for solver/method/weights."""

    payload = f"{solution.model_version}|{solution.method}|{solution.status}|" + ",".join(f"{key}:{value:.12f}" for key, value in solution.weights.items())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "METHODS",
    "METHOD_ALIASES",
    "OPTIMISER_MODEL_VERSION",
    "OptimiserConstraints",
    "OptimiserSolution",
    "PortfolioOptimiser",
    "optimiser_fingerprint",
    "returns_from_adjusted_prices",
]
