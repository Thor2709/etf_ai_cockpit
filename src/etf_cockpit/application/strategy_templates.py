"""Application facade for local strategy-template preferences and matches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import ROOT
from etf_cockpit.signals.strategy_templates import (
    StrategyTemplate,
    TemplateMatch,
    compute_template_matches,
    load_strategy_templates,
)


STATE_FILENAME = "strategy_templates_state.json"


class StrategyTemplateFacade:
    """Keep persistence and domain calls out of the rendering layer."""

    def __init__(self, root: Path | None = None, *, state_path: Path | None = None, registry_path: Path | None = None) -> None:
        self.root = root or ROOT
        self.state_path = state_path or self.root / "configs" / STATE_FILENAME
        self.registry_path = registry_path
        self.registry = load_strategy_templates(registry_path)
        self._enabled = self._read_enabled()

    @property
    def templates(self) -> tuple[StrategyTemplate, ...]:
        return self.registry

    @property
    def enabled(self) -> Mapping[str, bool]:
        return dict(self._enabled)

    def is_enabled(self, template_id: str) -> bool:
        self._require_template(template_id)
        return bool(self._enabled[template_id])

    def set_enabled(self, template_id: str, enabled: bool) -> None:
        self._require_template(template_id)
        self._enabled[template_id] = bool(enabled)
        payload = {"schema_version": 1, "enabled": dict(sorted(self._enabled.items()))}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_path, payload)

    def matches(self, snapshot: Iterable[Mapping[str, Any]] | object, *, decision_time: object | None = None) -> tuple[TemplateMatch, ...]:
        active = tuple(template for template in self.registry if self._enabled.get(template.template_id, True))
        return compute_template_matches(snapshot, active, decision_time=decision_time)  # type: ignore[arg-type]

    def _read_enabled(self) -> dict[str, bool]:
        enabled = {template.template_id: True for template in self.registry}
        if not self.state_path.is_file():
            return enabled
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            stored = payload.get("enabled", {}) if isinstance(payload, dict) else {}
            if isinstance(stored, dict):
                for template_id in enabled:
                    if template_id in stored and isinstance(stored[template_id], bool):
                        enabled[template_id] = stored[template_id]
        except (OSError, json.JSONDecodeError):
            return enabled
        return enabled

    def _require_template(self, template_id: str) -> None:
        if template_id not in self._enabled:
            raise KeyError(f"unknown strategy template: {template_id}")


def load_template_preferences(path: Path, template_ids: Iterable[str]) -> dict[str, bool]:
    """Read preferences without constructing a UI or contacting a provider."""

    facade = StrategyTemplateFacade(state_path=path, registry_path=Path(__file__).resolve().parents[3] / "configs" / "strategy_templates_v1.yaml")
    allowed = set(template_ids)
    return {template_id: value for template_id, value in facade.enabled.items() if template_id in allowed}


__all__ = ["STATE_FILENAME", "StrategyTemplateFacade", "load_template_preferences"]
