from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from etf_cockpit.core.paths import CONFIG_DIR


@dataclass(frozen=True)
class UIAcceptance:
    key: str
    route: str
    control_label: str
    callback: str
    success_signal: str
    controlled_error_signal: str


def load_ui_acceptance_contracts(path: Path | None = None) -> tuple[UIAcceptance, ...]:
    source = path or (CONFIG_DIR / "ui_acceptance.yaml")
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    rows = payload.get("controls")
    if not isinstance(rows, list):
        raise ValueError("ui acceptance controls must be a list")
    contracts: list[UIAcceptance] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ui acceptance record must be a mapping")
        values = {str(key): value for key, value in row.items()}
        contract = UIAcceptance(
            key=_required(values, "key"),
            route=_required(values, "route"),
            control_label=_required(values, "control_label"),
            callback=_required(values, "callback"),
            success_signal=_required(values, "success_signal"),
            controlled_error_signal=_required(values, "controlled_error_signal"),
        )
        if not contract.key.startswith(("navigation.", "dashboard.")):
            raise ValueError(f"unsupported UI acceptance key namespace: {contract.key}")
        contracts.append(contract)
    if len({item.key for item in contracts}) != len(contracts):
        raise ValueError("UI acceptance keys must be unique")
    return tuple(contracts)


def declared_keys(contracts: Iterable[UIAcceptance] | None = None) -> set[str]:
    return {item.key for item in contracts or load_ui_acceptance_contracts()}


def _required(values: dict[str, object], key: str) -> str:
    value = str(values.get(key) or "").strip()
    if not value:
        raise ValueError(f"missing UI acceptance field: {key}")
    return value
