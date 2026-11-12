"""Cockpit-side adapter for the independent Sparebank intelligence engine.

The adapter only imports complete immutable ``sparebank-intelligence-result.v1``
JSON envelopes from a configured local directory into the immutable run store and
serves the stored projection.  It runs no engine, needs no network and starts
cleanly when the directory, the store or the engine is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from etf_cockpit.data.sparebank_run_store import SparebankRunStore
from etf_cockpit.plugins.contracts import PluginContext, PluginHealth, PluginManifest, PluginResult, PluginStatus

SPAREBANK_MODEL_PLUGIN_ID = "sparebank.intelligence-model"


class SparebankModelAdapter:
    manifest = PluginManifest(
        plugin_id=SPAREBANK_MODEL_PLUGIN_ID,
        version="1.0.0",
        kind="model",
        capabilities=("health", "import", "intelligence"),
        licence="Project-local",
        network_access=False,
        quota="none",
        retention="immutable-local-run-store",
        authority="research_state",
    )

    def __init__(self, *, import_dir: Path | None = None, store_root: Path | None = None) -> None:
        self._import_dir = Path(import_dir) if import_dir is not None else None
        self._store = SparebankRunStore(store_root) if store_root is not None else None

    def health(self, _context: PluginContext) -> PluginHealth:
        if self._store is None or self._import_dir is None:
            return PluginHealth(status=PluginStatus.UNAVAILABLE, message="Sparebank intelligence import is not configured.")
        if not self._import_dir.is_dir():
            return PluginHealth(status=PluginStatus.UNAVAILABLE, message="Sparebank import directory is absent; no engine output imported.")
        return PluginHealth(status=PluginStatus.AVAILABLE, message="Sparebank import directory is readable; runs are advisory research state.")

    def import_data(self, _payload: Any, _context: PluginContext) -> PluginResult:
        if self._store is None or self._import_dir is None or not self._import_dir.is_dir():
            return PluginResult(status="unavailable", message="Sparebank import directory is not available.")
        report = self._store.import_directory(self._import_dir)
        summary = {status: report.count(status) for status in ("IMPORTED", "IDEMPOTENT", "QUARANTINED", "CONFLICT")}
        rows = [
            {"run_id": o.run_id, "status": o.status, "reasons": list(o.reasons)}
            for o in report.outcomes
            if o.status in {"QUARANTINED", "CONFLICT"}
        ]
        degraded = bool(summary["QUARANTINED"] or summary["CONFLICT"])
        return PluginResult(
            status="degraded" if degraded else "ok",
            message="Sparebank import finished with quarantined files." if degraded else "Sparebank import finished.",
            data={"summary": summary, "rejected": rows, "execution_allowed": False},
        )

    def intelligence(self, payload: Any, _context: PluginContext) -> PluginResult:
        """Return a stored run (``run_id``) or the latest verifiable one; unavailable when none exists."""

        if self._store is None:
            return PluginResult(status="unavailable", message="Sparebank run store is not configured.")
        requested = payload.get("run_id") if isinstance(payload, dict) else None
        run = self._store.get_run(str(requested)) if requested else self._store.latest_run()
        if run is None:
            return PluginResult(status="unavailable", message="No verifiable Sparebank intelligence run is available.")
        status = "ok" if run["status"] == "VALID" else "degraded"
        return PluginResult(status=status, message=f"Sparebank intelligence run {run['run_id']} ({run['status']}).", data={"run": run, "execution_allowed": False})


def register_sparebank_model(registry: Any, *, import_dir: Path | None, store_root: Path | None, enabled: bool = True) -> SparebankModelAdapter:
    """Register the adapter through the normal allow-listed ``PluginRegistry.register`` path."""

    adapter = SparebankModelAdapter(import_dir=import_dir, store_root=store_root)
    registry.register(adapter, enabled=enabled)
    return adapter


__all__ = ["SPAREBANK_MODEL_PLUGIN_ID", "SparebankModelAdapter", "register_sparebank_model"]
