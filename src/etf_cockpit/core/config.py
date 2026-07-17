from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from etf_cockpit.core.constants import ALLOWED_ROLES
from etf_cockpit.core.exceptions import ConfigError
from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.data.universe_store import import_legacy_universe, support_decision


class ETFConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    isin: str | None = None
    ticker: str
    provider_symbol: str | None = None
    exchange: str | None = None
    tradegate_ticker: str | None = None
    currency: str = "EUR"
    asset_class: str = "equity"
    region: str | None = None
    sector: str | None = None
    theme: str | None = None
    role: str
    accumulating: bool | None = None
    ucits: bool | None = None
    ter: float | None = None
    max_weight: float = 1.0
    min_history_days: int = 252
    enabled: bool = True
    instrument_type: str = "etf"
    analysis_tier: str = "primary"
    data_policy: str = "daily"
    source_group: str = ""
    isin_status: str = "verified"
    notes: str = ""
    # Compatibility defaults keep older YAML and persisted stores loadable.
    leveraged: bool = False
    inverse: bool = False

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in ALLOWED_ROLES:
            raise ValueError(f"role must be one of {ALLOWED_ROLES}")
        return value


class UniverseConfig(BaseModel):
    etfs: list[ETFConfig]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "UniverseConfig":
        ids = [etf.id for etf in self.etfs]
        if len(ids) != len(set(ids)):
            raise ValueError("ETF ids must be unique")
        return self

    @property
    def enabled_ids(self) -> list[str]:
        # The enabled universe is the scoring/provider boundary.  Research-
        # only, unsupported-frequency and high-risk records remain visible in
        # configuration but cannot silently enter normal workflows.
        return [
            etf.id
            for etf in self.etfs
            if etf.enabled
            and support_decision(etf.instrument_type, etf.data_policy, etf.leveraged, etf.inverse).score_eligible
        ]

    @property
    def configured_enabled_ids(self) -> list[str]:
        """Return enabled IDs including research/manual-review records."""
        return [etf.id for etf in self.etfs if etf.enabled]

    def by_id(self) -> dict[str, ETFConfig]:
        return {etf.id: etf for etf in self.etfs}


class TargetPosition(BaseModel):
    target_weight: float = Field(ge=0, le=1)
    soft_band: float = Field(default=0.03, ge=0, le=1)
    hard_band: float = Field(default=0.06, ge=0, le=1)


class PortfolioTargets(BaseModel):
    base_currency: str = "EUR"
    cash_min_weight: float = Field(default=0.02, ge=0, le=1)
    cash_target_weight: float = Field(default=0.05, ge=0, le=1)
    portfolio: dict[str, float] = Field(default_factory=dict)
    positions: dict[str, TargetPosition] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_total_target(self) -> "PortfolioTargets":
        total = sum(position.target_weight for position in self.positions.values()) + self.cash_target_weight
        if total > 1.05:
            raise ValueError(f"target weights plus cash exceed 105%: {total:.2%}")
        return self


class PortfolioLimits(BaseModel):
    max_single_etf_weight: float = 0.35
    max_sector_weight: float = 0.35
    max_region_weight: float = 0.70
    max_theme_weight: float = 0.25
    max_monthly_turnover: float = 0.25
    max_trade_fraction_of_portfolio: float = 0.15
    min_trade_value_eur: float = 100
    max_expected_drawdown_60d: float = 0.12
    min_edge_to_cost_ratio: float = 2.5
    cash_min_weight: float = 0.02


class SignalLimits(BaseModel):
    min_confidence_for_buy: float = 0.60
    min_confidence_for_trim: float = 0.55
    default_action: str = "no_trade"
    require_two_week_confirmation: bool = True
    no_trade_lower: float = -0.30
    no_trade_upper: float = 0.50
    add_threshold: float = 0.50
    strong_add_threshold: float = 0.75
    trim_threshold: float = -0.30
    sell_threshold: float = -0.75


class RiskLimits(BaseModel):
    portfolio_limits: PortfolioLimits = Field(default_factory=PortfolioLimits)
    signal_limits: SignalLimits = Field(default_factory=SignalLimits)


class CostModel(BaseModel):
    default_commission_eur: float = 1.0
    default_spread_bps: float = 8.0
    default_slippage_bps: float = 5.0
    fx_conversion_bps: float = 0.0
    min_edge_multiplier: float = 2.5
    impact_coefficient_bps: float = 25.0
    max_participation_rate: float = 0.10
    uncertainty_multiplier: float = 1.25
    gap_stress_bps: float = 0.0
    commission_stress_multiplier: float = 1.0
    model_version: str = "execution-cost-v1"


class CostConfig(BaseModel):
    base_currency: str = "EUR"
    broker: str = "local"
    cost_model: CostModel = Field(default_factory=CostModel)
    per_etf: dict[str, dict[str, float]] = Field(default_factory=dict)


class ModelRuntimeConfig(BaseModel):
    enabled: bool = False
    mode: Literal["disabled", "mock", "live"] = "disabled"
    backend: str = "auto"
    model_path: str | None = None
    hf_repo_id: str | None = None
    hf_repo_ids: dict[str, str] = Field(default_factory=dict)
    local_files_only: bool = True
    allow_remote_download: bool = False
    context_length: int = 2048
    use_quantiles: bool = True
    device: str = "auto"
    timeout_seconds: int = 60
    model_size: str | None = None
    decode_block_size: int = 768
    torch_compile: bool = False


class ModelSettings(BaseModel):
    forecast_horizons_trading_days: list[int] = Field(default_factory=lambda: [5, 20, 60, 120, 180])
    models: dict[str, Any] = Field(default_factory=dict)
    ensemble: dict[str, Any] = Field(default_factory=dict)

    def runtime(self, name: str) -> ModelRuntimeConfig:
        raw = self.models.get(name, {})
        return ModelRuntimeConfig(**raw)


class UISettings(BaseModel):
    theme_mode: str = "dark"
    window_width: int = 1400
    window_height: int = 900
    window_min_width: int = 1100
    window_min_height: int = 720
    default_page: str = "/"
    default_etf: str = "VWCE"


class ProviderSection(BaseModel):
    active_provider: str = "none"
    api_key: str = Field(default="", repr=False)
    base_url: str = ""
    symbols_map: dict[str, str] = Field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        return self.active_provider not in {"", "none"} and bool(self.base_url or self.symbols_map or self.api_key)

    def redacted(self) -> dict[str, Any]:
        data = self.model_dump()
        if data.get("api_key"):
            data["api_key"] = "***redacted***"
        return data


class DataProvidersConfig(BaseModel):
    providers: dict[str, ProviderSection] = Field(default_factory=dict)

    def section(self, name: str) -> ProviderSection:
        return self.providers.get(name, ProviderSection())

    def redacted(self) -> dict[str, Any]:
        return {"providers": {name: section.redacted() for name, section in self.providers.items()}}


class AppConfig(BaseModel):
    universe: UniverseConfig
    targets: PortfolioTargets
    risks: RiskLimits
    costs: CostConfig
    models: ModelSettings
    ui: UISettings
    chatgpt_schema: dict[str, Any]
    data_providers: DataProvidersConfig = Field(default_factory=DataProvidersConfig)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ConfigError(f"Could not read YAML config {path}: {exc}") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"Could not read JSON config {path}: {exc}") from exc


def load_config(config_dir: Path = CONFIG_DIR) -> AppConfig:
    try:
        provider_path = config_dir / "data_providers.yaml"
        data_providers = DataProvidersConfig(**(_read_yaml(provider_path) if provider_path.exists() else {}))
        data_providers = _apply_provider_env(data_providers, config_dir)
        return AppConfig(
            universe=_load_universe_config(config_dir),
            targets=PortfolioTargets(**(_read_yaml(config_dir / "portfolio_targets.yaml") if (config_dir / "portfolio_targets.yaml").exists() else {})),
            risks=RiskLimits(**(_read_yaml(config_dir / "risk_limits.yaml") if (config_dir / "risk_limits.yaml").exists() else {})),
            costs=CostConfig(**(_read_yaml(config_dir / "costs.yaml") if (config_dir / "costs.yaml").exists() else {})),
            models=ModelSettings(**(_read_yaml(config_dir / "model_settings.yaml") if (config_dir / "model_settings.yaml").exists() else {})),
            ui=UISettings(**(_read_yaml(config_dir / "ui_settings.yaml") if (config_dir / "ui_settings.yaml").exists() else {})),
            chatgpt_schema=_read_json(config_dir / "chatgpt_schema.json") if (config_dir / "chatgpt_schema.json").exists() else {},
            data_providers=data_providers,
        )
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"Config validation failed: {exc}") from exc


def _load_universe_config(config_dir: Path) -> UniverseConfig:
    persisted = config_dir / "universe_store.json"
    if not persisted.exists():
        primary_path = config_dir / "universe.yaml"
        if not primary_path.exists():
            return UniverseConfig(etfs=[])
        payload = _read_yaml(primary_path)
        candidate_dir = config_dir.parent / "data" / "raw" / "trade_candidates"
        candidates = sorted(candidate_dir.glob("yahoo_trade_candidates_*.csv")) if candidate_dir.exists() else []
        if candidates:
            imported = import_legacy_universe(primary_path, candidates[-1])
            return UniverseConfig(
                etfs=[
                    ETFConfig(
                        id=row.instrument_id,
                        name=row.name,
                        isin=None if row.isin_status == "needs_verification" else row.isin,
                        ticker=row.ticker,
                        provider_symbol=row.ticker,
                        exchange="OSE" if row.tier == "sparebanken" else None,
                        currency=row.currency,
                        asset_class="equity",
                        region=row.region or None,
                        sector=row.sector or None,
                        theme=row.theme or None,
                        role="core" if row.tier == "primary" else "watchlist",
                        enabled=row.enabled,
                        instrument_type=row.asset_type,
                        analysis_tier=row.tier,
                        data_policy=row.data_policy,
                        source_group=row.group,
                        isin_status=row.isin_status,
                        notes=row.notes,
                        leveraged=row.leveraged,
                        inverse=row.inverse,
                    )
                    for row in imported.records
                ]
            )
        normalised_etfs = []
        for raw in payload.get("etfs", ()):
            if not isinstance(raw, dict):
                normalised_etfs.append(raw)
                continue
            row = dict(raw)
            raw_isin = str(row.get("isin") or "").strip().lower()
            isin_status = str(row.get("isin_status") or "").strip().lower()
            if isin_status == "needs_verification" or raw_isin in {"", "unknown", "needs_verification"}:
                row["isin"] = None
            normalised_etfs.append(row)
        return UniverseConfig(**{**payload, "etfs": normalised_etfs})
    try:
        payload = _read_json(persisted)
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError("persisted universe must contain a records list")
        etfs: list[ETFConfig] = []
        for raw in records:
            if not isinstance(raw, dict):
                raise ValueError("persisted universe records must be objects")
            instrument_id = str(raw.get("instrument_id") or "").strip()
            ticker = str(raw.get("ticker") or "").strip()
            if not instrument_id or not ticker:
                raise ValueError("persisted universe records require instrument_id and ticker")
            isin_status = str(raw.get("isin_status") or "needs_verification").strip()
            raw_isin = str(raw.get("isin") or "").strip()
            isin = None if isin_status == "needs_verification" or raw_isin.lower() in {"", "unknown", "needs_verification"} else raw_isin
            asset_type = str(raw.get("asset_type") or "stock").strip().lower()
            tier = str(raw.get("tier") or "secondary").strip().lower()
            etfs.append(
                ETFConfig(
                    id=instrument_id,
                    name=str(raw.get("name") or instrument_id),
                    isin=isin,
                    ticker=ticker,
                    provider_symbol=ticker,
                    exchange="OSE" if asset_type in {"stock", "equity_certificate", "certificate"} else None,
                    currency=str(raw.get("currency") or "NOK"),
                    asset_class="equity",
                    region=str(raw.get("region") or "") or None,
                    sector=str(raw.get("sector") or "") or None,
                    theme=str(raw.get("theme") or "") or None,
                    role="core" if tier == "primary" else "watchlist",
                    ter=None,
                    max_weight=1.0,
                    min_history_days=252,
                    enabled=bool(raw.get("enabled", True)),
                    instrument_type=asset_type,
                    analysis_tier=tier,
                    data_policy=str(raw.get("data_policy") or "daily"),
                    source_group=str(raw.get("group") or ""),
                    isin_status=isin_status,
                    notes=str(raw.get("notes") or ""),
                    leveraged=_as_bool(raw.get("leveraged", False)),
                    inverse=_as_bool(raw.get("inverse", False)),
                )
            )
        return UniverseConfig(etfs=etfs)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ConfigError(f"Could not read persisted universe {persisted}: {exc}") from exc


def save_provider_settings(
    provider_name: str,
    *,
    active_provider: str,
    base_url: str,
    api_key: str = "",
    config_dir: Path = CONFIG_DIR,
) -> None:
    provider_key = provider_name.strip()
    if not provider_key:
        raise ConfigError("Provider name cannot be empty.")
    provider_path = config_dir / "data_providers.yaml"
    raw = _read_yaml(provider_path) if provider_path.exists() else {"providers": {}}
    providers = raw.setdefault("providers", {})
    current = providers.get(provider_key, {}) or {}
    current["active_provider"] = active_provider.strip() or "none"
    current["base_url"] = base_url.strip()
    current["api_key"] = ""
    current.setdefault("symbols_map", {})
    providers[provider_key] = current
    provider_path.parent.mkdir(parents=True, exist_ok=True)
    provider_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    if api_key.strip():
        _write_env_value(config_dir.parent / ".env", _provider_env_key(provider_key, "API_KEY"), api_key.strip())


def _apply_provider_env(config: DataProvidersConfig, config_dir: Path) -> DataProvidersConfig:
    env_file_values = {key: value for key, value in dotenv_values(config_dir.parent / ".env").items() if value is not None}
    provider_names = set(config.providers) | {"prices", "fx", "etf_metadata", "etf_holdings"}
    providers = {name: section.model_copy(deep=True) for name, section in config.providers.items()}
    for name in provider_names:
        section = providers.get(name, ProviderSection())
        updates: dict[str, Any] = {}
        active_provider = _env_value(_provider_env_key(name, "PROVIDER"), env_file_values)
        base_url = _env_value(_provider_env_key(name, "BASE_URL"), env_file_values)
        api_key = _env_value(_provider_env_key(name, "API_KEY"), env_file_values)
        if active_provider is not None:
            updates["active_provider"] = active_provider
        if base_url is not None:
            updates["base_url"] = base_url
        if api_key is not None:
            updates["api_key"] = api_key
        if updates:
            providers[name] = section.model_copy(update=updates)
    return DataProvidersConfig(providers=providers)


def _provider_env_key(provider_name: str, suffix: str) -> str:
    prefix = provider_name.strip().upper().replace("-", "_").replace(" ", "_")
    return f"ETF_COCKPIT_{prefix}_{suffix}"


def _env_value(key: str, env_file_values: dict[str, str]) -> str | None:
    value = os.getenv(key)
    if value is not None:
        return value
    return env_file_values.get(key)


def _write_env_value(env_path: Path, key: str, value: str) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    new_line = f'{key}="{_escape_env_value(value)}"'
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[index] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _escape_env_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)
