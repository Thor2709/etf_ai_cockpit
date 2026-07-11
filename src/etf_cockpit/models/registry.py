from __future__ import annotations

from etf_cockpit.core.config import AppConfig
from etf_cockpit.models.local_weights import LocalModelStatus, model_weight_inventory


def model_availability(config: AppConfig) -> dict[str, bool]:
    inventory = model_weight_inventory(config)
    return {
        "baseline": True,
        "timesfm": any(status.model_name == "timesfm" and status.live_ready for status in inventory),
        "toto": any(status.model_name == "toto" and status.live_ready for status in inventory),
    }


def model_diagnostics(config: AppConfig) -> list[LocalModelStatus]:
    return model_weight_inventory(config)
