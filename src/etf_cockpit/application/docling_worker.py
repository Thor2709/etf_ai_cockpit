"""Optional Docling PDF layout/table worker (INT-24), run as a bounded child process.

pdfplumber/pypdf stay the default parsers; this worker only adds layout-aware tables, and its tables enter the
Pillar 3 review queue as unreviewed (pending) evidence. The child runs offline (no download of any kind, sockets
denied), under a time limit and a memory limit, and every outcome is an explicit status: ``ok``, ``unavailable``,
``timeout``, ``memory_limit`` or ``error``. Weights load only from hash-verified local files
(``configs/document_model_weights.yaml``); a missing or mismatched file keeps the feature unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

import yaml

from etf_cockpit.core.atomic_io import sha256_file
from etf_cockpit.core.paths import CONFIG_DIR, MODEL_DIR

WEIGHTS_CONFIG = CONFIG_DIR / "document_model_weights.yaml"
TABLE_METRIC = "docling_table"
MEMORY_EXIT_CODE = 97
PROBE_EXIT_CODE = 96  # the memory probe failed: the child stops (fail closed) and the parent reports an error
_WEIGHT_SUFFIXES = (".safetensors", ".onnx", ".pt", ".bin")
_LAYOUT_REPOSITORY = "docling-layout-heron"
_OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "CUDA_VISIBLE_DEVICES": "", "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"}


@dataclass(frozen=True)
class DoclingResult:
    status: str  # ok | unavailable | timeout | memory_limit | error
    reason: str = ""
    pages: tuple[str, ...] = ()  # text per page, for the INT-23 chunker
    tables: tuple[dict[str, object], ...] = ()
    ocr: str = "disabled"


def _docling_available() -> bool:
    return importlib.util.find_spec("docling") is not None


def _base(package: str, model_dir: Path) -> Path:
    if not package:
        return Path(model_dir)
    spec = importlib.util.find_spec(package)
    return Path(next(iter(spec.submodule_search_locations or ()), "")) if spec else Path()


def verify_weights(model_dir: Path, config_path: Path = WEIGHTS_CONFIG, *, packaged: bool = False) -> str:
    """Empty string when every listed file exists and matches its sha256, else the first failure.

    ``packaged`` selects the OCR files shipped inside a wheel; the others live under ``model_dir``. A weight file
    in a pinned folder that is not listed is a failure too, because the libraries load the first match.
    """

    rows = [row for row in yaml.safe_load(config_path.read_text(encoding="utf-8"))["weights"] if bool(row.get("package")) == packaged]
    pinned = {(str(row.get("package") or ""), row["path"]) for row in rows}
    for package, folder in sorted({(str(row.get("package") or ""), row["path"].split("/")[0]) for row in rows}):
        base = _base(package, model_dir)
        for found in sorted((base / folder).rglob("*")):
            relative = found.relative_to(base).as_posix()
            if found.is_file() and found.suffix.lower() in _WEIGHT_SUFFIXES and (package, relative) not in pinned:
                return f"weight_unpinned:{relative}"
    for row in rows:
        path = _base(str(row.get("package") or ""), model_dir) / row["path"]
        if not path.is_file():
            return f"weight_missing:{row['path']}"
        if sha256_file(path) != row["sha256"]:
            return f"weight_hash_mismatch:{row['path']}"
    return ""


def run_docling(
    pdf_path: Path,
    *,
    model_dir: Path | None = None,
    timeout_seconds: float | None = None,
    memory_limit_mb: int | None = None,
    argv: list[str] | None = None,
) -> DoclingResult:
    """Convert one PDF in a child process. ``argv`` replaces the child command (test seam: skips the readiness checks)."""

    model_dir = Path(model_dir) if model_dir is not None else MODEL_DIR / "docling"
    if argv is None:
        if not _docling_available():
            return DoclingResult("unavailable", "docling_not_installed")
        failure = verify_weights(model_dir)
        if failure:
            return DoclingResult("unavailable", failure)
    if timeout_seconds is None or memory_limit_mb is None:
        from etf_cockpit.core.resource_profiles import document_worker_limits

        default_memory, default_seconds = document_worker_limits()
        memory_limit_mb = default_memory if memory_limit_mb is None else memory_limit_mb
        timeout_seconds = default_seconds if timeout_seconds is None else timeout_seconds
    with tempfile.TemporaryDirectory(prefix="docling-worker-") as scratch:
        result_path = Path(scratch) / "result.json"
        request = Path(scratch) / "request.json"
        request.write_text(json.dumps({"pdf": str(pdf_path), "model_dir": str(model_dir), "memory_limit_mb": memory_limit_mb, "result": str(result_path)}), encoding="utf-8")
        command = argv or [sys.executable, "-m", __name__, str(request)]
        env = {**os.environ, **_OFFLINE_ENV, "PYTHONPATH": os.pathsep.join(entry for entry in sys.path if entry)}  # the child imports what the parent imports
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return DoclingResult("timeout", f"exceeded_{timeout_seconds:g}_seconds")
        finally:  # a timeout or any other interruption never leaves the child running
            if process.poll() is None:
                process.kill()
            process.wait()
        if code == MEMORY_EXIT_CODE:
            return DoclingResult("memory_limit", f"exceeded_{memory_limit_mb}_mb")
        if code == PROBE_EXIT_CODE:
            return DoclingResult("error", "memory_probe_failed")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return DoclingResult("error", f"child_exit_{code}_without_result")
    if payload.get("status") != "ok":
        return DoclingResult("error", str(payload.get("reason") or "conversion_failed")[:300])
    return DoclingResult("ok", "", tuple(payload["pages"]), tuple(payload["tables"]), str(payload.get("ocr", "disabled")))


def queue_tables(
    root: Path,
    instrument_id: str,
    pdf_path: Path,
    *,
    source_url: str,
    model_dir: Path | None = None,
    timeout_seconds: float | None = None,
    memory_limit_mb: int | None = None,
) -> dict[str, object]:
    """Run the worker and add each table to the Pillar 3 review queue as a pending (unreviewed) figure."""

    from etf_cockpit.data.pillar3_queue import merge_extraction

    if not str(source_url).startswith("https://"):
        raise ValueError("source_url must be an https URL of the issuer or regulator document")
    result = run_docling(Path(pdf_path), model_dir=model_dir, timeout_seconds=timeout_seconds, memory_limit_mb=memory_limit_mb)
    if result.status != "ok":
        return {"status": result.status, "reason": result.reason, "proposed": 0}
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    document = {"document_id": digest[:16], "source_url": source_url, "title": Path(pdf_path).name, "sha256": digest, "pages": len(result.pages), "extractor": f"docling-{_docling_version()}"}
    figures = []
    for index, table in enumerate(result.tables):  # document order is stable, so identical tables keep distinct ids
        key = hashlib.sha256(f"{digest}|{index}|{table['page']}|{table['markdown']}".encode("utf-8")).hexdigest()[:12]
        # A unique period key keeps one confirmed table from superseding another; no period matches a scorecard period.
        figures.append({"figure_id": f"{TABLE_METRIC}:{key}", "metric": TABLE_METRIC, "label": f"Table on page {table['page']}", "value": None, "unit": "",
                        "period": f"table:{key}", "page": table["page"], "printed_text": table["markdown"], "flags": ["docling_table", "unreviewed"],
                        "rows": table["rows"], "columns": table["columns"]})
    merge_extraction(Path(root), instrument_id, document, figures)
    return {"status": "ok", "reason": "", "proposed": len(figures), "ocr": result.ocr}


def _docling_version() -> str:
    from importlib import metadata

    try:
        return metadata.version("docling-slim")
    except metadata.PackageNotFoundError:
        return "unknown"


def _rss_mb() -> float:
    """Resident memory of this process in MB (no dependency)."""

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD), ("peak", ctypes.c_size_t), ("working_set", ctypes.c_size_t)] + [(f"q{i}", ctypes.c_size_t) for i in range(6)]

        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
        if not kernel.K32GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("process memory probe failed")
        return counters.working_set / 1_048_576
    with open("/proc/self/statm", encoding="ascii") as handle:
        return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1_048_576


def start_memory_watchdog(limit_mb: float, interval: float = 0.2) -> None:
    """End this process with ``MEMORY_EXIT_CODE`` once its resident memory passes ``limit_mb`` (``PROBE_EXIT_CODE`` if unmeasurable)."""

    def watch() -> None:
        while True:
            try:
                over = _rss_mb() > limit_mb
            except Exception:  # noqa: BLE001 - an unmeasurable child is stopped, not left unbounded
                os._exit(PROBE_EXIT_CODE)
            if over:
                os._exit(MEMORY_EXIT_CODE)
            time.sleep(interval)

    threading.Thread(target=watch, daemon=True).start()


def _deny_network() -> None:
    """Child-process guard: socket connections and getaddrinfo lookups raise (the weights are local; no run-time download)."""

    import socket

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("network access is denied in the document worker")

    socket.socket.connect = refuse  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign,assignment]
    socket.getaddrinfo = refuse  # type: ignore[assignment]
    socket.create_connection = refuse  # type: ignore[assignment]


def _convert(pdf: str, model_dir: Path) -> dict[str, object]:
    """Docling conversion inside the child. Layout and table weights are local; OCR uses the wheel's ONNX files."""

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.layout_model_specs import LayoutModelConfig
    from docling.datamodel.pipeline_options import LayoutOptions, PdfPipelineOptions, RapidOcrOptions, TableFormerMode, TableStructureOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.models.stages.table_structure.table_structure_model import TableStructureModel

    rows = yaml.safe_load(WEIGHTS_CONFIG.read_text(encoding="utf-8"))["weights"]
    layout = next(row for row in rows if _LAYOUT_REPOSITORY in row["path"] and not row.get("package"))
    # Docling looks for "<repo with / replaced by -->" folders; the local folders carry the plain repository name.
    TableStructureModel._model_repo_folder = "docling-models"
    ocr_status = verify_weights(model_dir, packaged=True)
    ocr_options = RapidOcrOptions(lang=["en"])
    if not ocr_status:
        import rapidocr

        package_models = Path(rapidocr.__file__).parent / "models"
        ocr_options = RapidOcrOptions(
            backend="onnxruntime", lang=["en"], det_model_path=str(package_models / "PP-OCRv6_det_small.onnx"),
            rec_model_path=str(package_models / "PP-OCRv6_rec_small.onnx"), cls_model_path=str(package_models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
        )
    options = PdfPipelineOptions(
        artifacts_path=model_dir, do_ocr=not ocr_status, ocr_options=ocr_options, do_table_structure=True,
        layout_options=LayoutOptions(model_spec=LayoutModelConfig(name="docling_layout_heron", repo_id=_LAYOUT_REPOSITORY, revision=layout["revision"])),
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
        allow_external_plugins=False, enable_remote_services=False,
    )
    document = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}).convert(pdf).document
    page_count = max(document.pages) if document.pages else 0
    pages = [""] * page_count
    for item in document.texts:
        if item.prov and item.text:
            index = item.prov[0].page_no - 1
            pages[index] = f"{pages[index]}\n{item.text}".strip()
    tables = []
    for table in document.tables:
        if not table.prov:
            continue  # no page provenance: not proposed
        tables.append({"page": table.prov[0].page_no, "rows": table.data.num_rows, "columns": table.data.num_cols, "markdown": table.export_to_markdown(document)[:8000]})
    return {"status": "ok", "pages": pages, "tables": tables, "ocr": "disabled: " + ocr_status if ocr_status else "enabled_bitmap_regions_only"}


def _child_main(request_path: str) -> int:
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    os.environ.update(_OFFLINE_ENV)
    _deny_network()
    start_memory_watchdog(float(request["memory_limit_mb"]))
    try:
        payload = _convert(request["pdf"], Path(request["model_dir"]))
    except MemoryError:
        return MEMORY_EXIT_CODE
    except Exception as exc:  # noqa: BLE001 - every failure becomes an explicit status in the parent
        payload = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    Path(request["result"]).write_text(json.dumps(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(_child_main(sys.argv[1]))
