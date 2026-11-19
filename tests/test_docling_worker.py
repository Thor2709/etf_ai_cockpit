from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
import yaml

from etf_cockpit.application import docling_worker as dw
from etf_cockpit.core.paths import MODEL_DIR
from etf_cockpit.data.pillar3_queue import load_queue

ROOT = Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
KID = ROOT / "tests" / "fixtures" / "official" / "priips_kid" / "vanguard-ie000q4j3cw6-priips-kid.pdf"
# The weights are not in git; ETF_DOCLING_MODEL_DIR points to a checkout that holds them.
WEIGHTS = Path(os.environ.get("ETF_DOCLING_MODEL_DIR", MODEL_DIR / "docling"))


def _env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [SRC, os.environ.get("PYTHONPATH")]))}


def test_importing_the_worker_never_imports_docling() -> None:
    code = "import sys\nimport etf_cockpit.application.docling_worker, etf_cockpit.application.document_parsers\nsys.exit('docling' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], env=_env(), capture_output=True, timeout=120).returncode == 0


def test_absent_docling_gives_unavailable_and_parsers_stay_untouched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dw, "_docling_available", lambda: False)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    result = dw.run_docling(pdf, model_dir=tmp_path)

    assert (result.status, result.reason) == ("unavailable", "docling_not_installed")
    assert dw.queue_tables(tmp_path, "X", pdf, source_url="https://example.com/a.pdf", model_dir=tmp_path)["status"] == "unavailable"
    assert load_queue(tmp_path, "X")["figures"] == []


def test_weights_are_hash_verified_per_file(tmp_path: Path) -> None:
    model = tmp_path / "m"
    model.mkdir()
    (model / "w.bin").write_bytes(b"weights")
    config = tmp_path / "weights.yaml"
    row = {"path": "m/w.bin", "bytes": 7, "sha256": hashlib.sha256(b"weights").hexdigest()}
    config.write_text(yaml.safe_dump({"schema_version": "document-model-weights.v1", "weights": [row]}), encoding="utf-8")

    assert dw.verify_weights(tmp_path, config) == ""
    (model / "w.bin").write_bytes(b"tampered")
    assert dw.verify_weights(tmp_path, config) == "weight_hash_mismatch:m/w.bin"
    (model / "w.bin").write_bytes(b"weights")
    (model / "sibling.onnx").write_bytes(b"x")
    assert dw.verify_weights(tmp_path, config) == "weight_unpinned:m/sibling.onnx"
    (model / "sibling.onnx").unlink()
    (model / "w.bin").unlink()
    assert dw.verify_weights(tmp_path, config) == "weight_missing:m/w.bin"


def test_weight_inventory_row_per_file_matches_source_records() -> None:
    rows = yaml.safe_load(dw.WEIGHTS_CONFIG.read_text(encoding="utf-8"))["weights"]

    assert len(rows) == 9 and all(len(row["sha256"]) == 64 and row["revision"] and row["licence"] and row["repository"] for row in rows)
    for source in (WEIGHTS / "docling-layout-heron" / "SOURCE.json", WEIGHTS / "docling-models" / "SOURCE.json"):
        if not source.is_file():
            continue
        import json

        recorded = {Path(item["file"]).relative_to("models/docling").as_posix(): item["sha256"] for item in json.loads(source.read_text(encoding="utf-8"))["files"]}
        assert {row["path"]: row["sha256"] for row in rows if row["path"] in recorded} == recorded


def test_child_guard_denies_every_network_connection() -> None:
    code = "import socket\nfrom etf_cockpit.application.docling_worker import _deny_network\n_deny_network()\nsocket.create_connection(('127.0.0.1', 9))"
    result = subprocess.run([sys.executable, "-c", code], env=_env(), capture_output=True, text=True, timeout=120)

    assert result.returncode == 1 and "network access is denied" in result.stderr


def test_timeout_gives_a_clean_status_and_kills_the_child(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    started = time.monotonic()
    result = dw.run_docling(pdf, model_dir=tmp_path, timeout_seconds=1, argv=[sys.executable, "-c", "import time; time.sleep(60)"])

    assert result.status == "timeout" and time.monotonic() - started < 30


@pytest.mark.parametrize("code, status, reason", [
    ("from etf_cockpit.application.docling_worker import start_memory_watchdog\nstart_memory_watchdog(1)\ntime.sleep(30)", "memory_limit", "exceeded_"),
    ("import etf_cockpit.application.docling_worker as w\nw._rss_mb = lambda: 1 / 0\nw.start_memory_watchdog(100)\ntime.sleep(30)", "error", "memory_probe_failed"),
], ids=["over_limit", "failing_probe"])
def test_memory_watchdog_stops_the_child_with_a_clean_status(code: str, status: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setenv("PYTHONPATH", _env()["PYTHONPATH"])

    result = dw.run_docling(pdf, model_dir=tmp_path, timeout_seconds=60, argv=[sys.executable, "-c", "import time\n" + code])

    assert result.status == status and result.reason.startswith(reason)


def test_tables_enter_the_review_queue_as_pending_with_page_provenance_and_identical_tables_stay_distinct(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    table = {"page": 3, "rows": 2, "columns": 2, "markdown": "| a | b |\n| 1 | 2 |"}
    monkeypatch.setattr(dw, "run_docling", lambda *_a, **_k: dw.DoclingResult("ok", pages=("", "", "text"), tables=(table, dict(table))))
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    assert dw.queue_tables(tmp_path, "X", pdf, source_url="https://example.com/a.pdf")["proposed"] == 2
    figures = load_queue(tmp_path, "X")["figures"]

    assert all((f["metric"], f["status"], f["page"], f["printed_text"]) == (dw.TABLE_METRIC, "pending", 3, table["markdown"]) for f in figures)
    assert len(figures) == 2 and len({item["figure_id"] for item in figures}) == 2 and len({item["period"] for item in figures}) == 2


def test_an_interrupted_parent_never_leaves_the_child_running(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    started: list[subprocess.Popen[bytes]] = []
    real = subprocess.Popen

    class Interrupted(real):  # type: ignore[type-arg,misc]
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[call-overload]
            started.append(self)

        def wait(self, timeout: float | None = None) -> int:
            if timeout is not None:
                raise KeyboardInterrupt
            return super().wait()

    monkeypatch.setattr(dw.subprocess, "Popen", Interrupted)
    try:
        with pytest.raises(KeyboardInterrupt):
            dw.run_docling(pdf, model_dir=tmp_path, timeout_seconds=60, argv=[sys.executable, "-c", "import time; time.sleep(60)"])
        assert started[0].poll() is not None
    finally:
        started[0].kill()


def test_fixture_table_reaches_the_review_queue_with_page_provenance_offline(tmp_path: Path) -> None:
    pytest.importorskip("docling")
    if not (WEIGHTS / "docling-models").is_dir():
        pytest.skip("docling weights are not available")
    out = dw.queue_tables(tmp_path, "KID1", KID, source_url="https://example.com/kid.pdf", model_dir=WEIGHTS, memory_limit_mb=6144, timeout_seconds=600)

    assert out["status"] == "ok", out
    figures = [item for item in load_queue(tmp_path, "KID1")["figures"] if item["metric"] == dw.TABLE_METRIC]
    assert figures and all(item["status"] == "pending" and item["page"] >= 1 and item["printed_text"] for item in figures)
