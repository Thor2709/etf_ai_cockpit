from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_repo_pytest_temp = ROOT / "logs" / "pytest_system_tmp"
if os.name == "nt" and len(str(_repo_pytest_temp)) > 90:
    # Linked worktrees can exceed Windows' legacy path limit before the test
    # payload is created. Keep the same deterministic case layout in the
    # system temp directory when the repository path itself is too long.
    PYTEST_TEMP = Path(tempfile.gettempdir()) / "etf_ai_cockpit_pytest"
else:
    PYTEST_TEMP = _repo_pytest_temp
PYTEST_TEMP.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(PYTEST_TEMP)
os.environ["TMP"] = str(PYTEST_TEMP)
os.environ["TMPDIR"] = str(PYTEST_TEMP)
tempfile.tempdir = str(PYTEST_TEMP)

_XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
if _XDIST_WORKER:
    # Each worker is one of many CPU-bound processes: nested BLAS/OpenMP pools only oversubscribe.
    for _thread_variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(_thread_variable, "1")

# --- Per-process project root ---------------------------------------------------------------
# Product code resolves every mutable path (data/, logs/, exports/, backups/, artifacts/) from the
# project root.  Tests used to share the checkout's real root, so parallel workers raced on the same
# SQLite store, parquet files and file guards, and serial runs mutated local developer data.  Every
# pytest process now gets a private root before etf_cockpit is imported: mutable directories hold
# fresh copies of their tracked files only (the state of a clean CI checkout) and every other
# top-level entry is linked to the checkout.  Writes through those links are rejected by
# _repo_write_guard below.
ISOLATED_ROOTS = PYTEST_TEMP / "project_roots"
_PRIVATE_DIRECTORIES = ("configs", "data", "artifacts", "logs", "exports", "backups")
_UNLINKED_ENTRIES = {".hypothesis", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache"}
# A root whose heartbeat (touched after every test) is older than this belongs to a finished or
# killed session: a failing run's roots stay inspectable for this long, then the next session prunes them.
_STALE_ROOT_SECONDS = 30 * 60
_HEARTBEAT = ".pytest-heartbeat"


def _is_link(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path)


def _remove_isolated_root(root: Path) -> None:
    """Delete an isolated root without ever following a link into the checkout."""

    root = Path(os.path.abspath(root))
    if root.parent != Path(os.path.abspath(ISOLATED_ROOTS)):
        raise RuntimeError(f"refusing to remove a path outside {ISOLATED_ROOTS}: {root}")
    if _is_link(root) or not root.is_dir():
        return
    for entry in root.iterdir():
        if _is_link(entry):
            # Removes the link itself: rmdir for a junction, unlink for a symlink.
            if os.path.isjunction(entry):
                os.rmdir(entry)
            else:
                os.unlink(entry)
    shutil.rmtree(root)


def _prune_stale_isolated_roots() -> None:
    if not ISOLATED_ROOTS.is_dir():
        return
    cutoff = time.time() - _STALE_ROOT_SECONDS
    for candidate in ISOLATED_ROOTS.iterdir():
        try:
            heartbeat = candidate / _HEARTBEAT
            if (heartbeat if heartbeat.exists() else candidate).stat().st_mtime < cutoff:
                _remove_isolated_root(candidate)
        except OSError:
            continue  # still in use, or removed by a concurrent session


def _tracked_files(directories: tuple[str, ...]) -> list[str] | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z", "--", *directories],
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [item for item in completed.stdout.decode("utf-8").split("\0") if item]


def _link(source: Path, destination: Path) -> None:
    if source.is_dir():
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(source), str(destination))
        else:
            destination.symlink_to(source, target_is_directory=True)
    else:
        # A copy, not a hard link: a write through a hard link would silently reach the checkout.
        shutil.copy2(source, destination)


def _create_isolated_root() -> Path:
    ISOLATED_ROOTS.mkdir(parents=True, exist_ok=True)
    root = ISOLATED_ROOTS / f"{_XDIST_WORKER or 'main'}-{uuid.uuid4().hex[:8]}"
    root.mkdir()
    for entry in ROOT.iterdir():
        if entry.name not in _PRIVATE_DIRECTORIES and entry.name not in _UNLINKED_ENTRIES:
            _link(entry, root / entry.name)
    tracked = _tracked_files(_PRIVATE_DIRECTORIES)
    if tracked is None:
        # No git metadata (e.g. an extracted source distribution): copy configuration only.
        tracked = [path.relative_to(ROOT).as_posix() for path in (ROOT / "configs").rglob("*") if path.is_file()]
    for relative in tracked:
        source = ROOT / relative
        if source.is_file():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for name in _PRIVATE_DIRECTORIES:
        (root / name).mkdir(exist_ok=True)
    (root / _HEARTBEAT).touch()
    return root


_prune_stale_isolated_roots()
ISOLATED_ROOT = _create_isolated_root()
os.environ["ETF_COCKPIT_ROOT"] = str(ISOLATED_ROOT)

# --- Seeded project data ----------------------------------------------------------------------
# The first build_snapshot() in an empty data/ generates the sample dataset (~45 s).  Serially that
# cost is paid once and every later test sees the populated data; with one root per worker it
# would be paid by every worker.  So the dataset is built once per source state (keyed by a hash of
# src/, configs/ and tracked data) and copied into each root before collection: the same state a
# serial run reaches after its first snapshot.  If the seed cannot be built, data/ stays empty.
DATA_SEEDS = PYTEST_TEMP / "data_seeds"
_SEED_BUILD_TIMEOUT_SECONDS = 900
_SEED_KEEP = 2


def _seed_key() -> str:
    import hashlib

    digest = hashlib.sha256(sys.version.encode("utf-8"))
    tracked_data = _tracked_files(("data",)) or []
    sources = sorted(
        [*(ROOT / "src").rglob("*.py"), *(path for path in (ROOT / "configs").rglob("*") if path.is_file())]
        + [ROOT / relative for relative in tracked_data]
    )
    for path in sources:
        if path.is_file():
            digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _build_data_seed(seed: Path) -> None:
    lock = DATA_SEEDS / f"{seed.name}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime > _SEED_BUILD_TIMEOUT_SECONDS:
            lock.unlink(missing_ok=True)  # abandoned by a killed session
        return
    os.close(descriptor)
    builder = _create_isolated_root()
    try:
        environment = {**os.environ, "ETF_COCKPIT_ROOT": str(builder), "ETF_COCKPIT_OFFLINE": "1"}
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "src"), environment.get("PYTHONPATH")]))
        completed = subprocess.run(
            [sys.executable, "-c", "from etf_cockpit.services import build_snapshot; build_snapshot()"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=_SEED_BUILD_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            print(f"warning: data seed build failed; tests start from empty data/\n{completed.stderr[-2000:]}", file=sys.stderr)
            return
        staging = DATA_SEEDS / f"{seed.name}.staging-{uuid.uuid4().hex[:8]}"
        shutil.copytree(builder / "data", staging / "data")
        os.replace(staging, seed)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"warning: data seed build failed ({exc}); tests start from empty data/", file=sys.stderr)
    finally:
        lock.unlink(missing_ok=True)
        _remove_isolated_root(builder)


def _seed_isolated_data() -> None:
    DATA_SEEDS.mkdir(parents=True, exist_ok=True)
    seed = DATA_SEEDS / _seed_key()
    deadline = time.monotonic() + _SEED_BUILD_TIMEOUT_SECONDS
    while not seed.is_dir() and time.monotonic() < deadline:
        _build_data_seed(seed)
        if not seed.is_dir():
            if not (DATA_SEEDS / f"{seed.name}.lock").exists():
                break  # the build failed; do not retry in every process
            time.sleep(0.5)  # another process is building it
    if seed.is_dir():
        shutil.copytree(seed / "data", ISOLATED_ROOT / "data", dirs_exist_ok=True)
    for stale in sorted(
        (path for path in DATA_SEEDS.iterdir() if path.is_dir() and "." not in path.name),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[_SEED_KEEP:]:
        shutil.rmtree(stale, ignore_errors=True)


def pytest_configure(config: pytest.Config) -> None:
    if config.option.collectonly:
        return  # collection never reads project data
    try:
        _seed_isolated_data()
    except OSError as exc:
        print(f"warning: could not seed isolated data ({exc}); tests start from empty data/", file=sys.stderr)


# --- Checkout write guard -------------------------------------------------------------------
# Any write that resolves into the real checkout (outside pytest's own temp tree and caches)
# fails the test that made it.  This keeps the isolation above from regressing silently.
_REAL_ROOT = os.path.normcase(os.path.realpath(ROOT))
_GUARD_EXEMPT = tuple(
    os.path.normcase(os.path.realpath(path)) + os.sep
    for path in (PYTEST_TEMP, ROOT / ".hypothesis", ROOT / "logs" / "runtime_tmp")
)
# flet_app._startup_log appends to <cwd>/logs/startup.log by design (launcher diagnostics).
_GUARD_EXEMPT_FILES = {os.path.normcase(os.path.realpath(ROOT / "logs" / "startup.log"))}
_WRITE_EVENTS = {"os.remove", "os.rename", "os.replace", "os.rmdir", "shutil.rmtree", "shutil.move", "shutil.copyfile", "os.truncate"}
_guard_state: dict[str, object] = {"active": False, "violations": []}


def _checkout_write(path: object, dir_fd: object = None) -> str | None:
    if isinstance(path, int) or path is None:
        return None
    try:
        name = os.fsdecode(path)
        if isinstance(dir_fd, int) and dir_fd >= 0 and not os.path.isabs(name):
            # fd-relative call (e.g. Linux shutil.rmtree): resolve against that directory, not cwd.
            try:
                name = os.path.join(os.readlink(f"/proc/self/fd/{dir_fd}"), name)
            except OSError:
                return None  # directory unknown on this platform: cannot attribute the write
        resolved = os.path.normcase(os.path.realpath(name))
    except (TypeError, ValueError, OSError):
        return None
    if resolved != _REAL_ROOT and not resolved.startswith(_REAL_ROOT + os.sep):
        return None
    if resolved.startswith(_GUARD_EXEMPT) or resolved in _GUARD_EXEMPT_FILES or f"{os.sep}__pycache__" in resolved:
        return None
    return resolved


def _write_guard_hook(event: str, args: tuple[object, ...]) -> None:
    if not _guard_state["active"]:
        return
    if event == "open":
        mode, flags = args[1], args[2]
        writing = (isinstance(mode, str) and any(flag in mode for flag in "wax+")) or (
            mode is None and isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        )
        paths = (args[0],) if writing else ()
    elif event == "os.mkdir":
        directory_fd = args[2] if len(args) > 2 else None
        exists = isinstance(directory_fd, int) and directory_fd >= 0 or os.path.isdir(os.fsdecode(args[0]))
        paths = () if exists else ((args[0], directory_fd),)
    elif event == "sqlite3.connect":
        database = os.fsdecode(args[0]) if isinstance(args[0], (str, bytes, os.PathLike)) else ""
        if database.startswith("file:"):
            location, _, query = database[len("file:") :].partition("?")
            read_only = "mode=ro" in query.split("&") or "immutable=1" in query.split("&")
            paths = () if read_only or location in ("", ":memory:") else (location,)
        else:
            paths = () if database in ("", ":memory:") else (database,)
    elif event in _WRITE_EVENTS:
        if event == "shutil.copyfile":
            paths = (args[1],)  # the source is only read
        elif event in ("os.rename", "os.replace"):
            # (src, dst, src_dir_fd, dst_dir_fd): the source disappears, the destination is written
            paths = ((args[0], args[2] if len(args) > 2 else None), (args[1], args[3] if len(args) > 3 else None))
        elif event == "shutil.move":
            paths = args[:2]
        else:
            paths = ((args[0], args[1] if len(args) > 1 else None),)  # (path, dir_fd)
    else:
        return
    for entry in paths:
        path, directory_fd = entry if isinstance(entry, tuple) else (entry, None)
        resolved = _checkout_write(path, directory_fd)
        if resolved is not None:
            _guard_state["violations"].append(f"{event}: {resolved}")  # type: ignore[union-attr]


sys.addaudithook(_write_guard_hook)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    _guard_state["violations"] = []
    _guard_state["active"] = True
    try:
        yield
    finally:
        _guard_state["active"] = False


@pytest.fixture(autouse=True)
def _repo_write_guard() -> Iterator[None]:
    yield
    try:
        os.utime(ISOLATED_ROOT / _HEARTBEAT)
    except OSError:
        pass
    violations = sorted(set(_guard_state["violations"]))  # type: ignore[arg-type]
    if violations:
        pytest.fail(
            "test wrote into the real checkout instead of its isolated project root or tmp_path:\n  "
            + "\n  ".join(violations[:20]),
            pytrace=False,
        )


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    path = PYTEST_TEMP / "cases" / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    request.addfinalizer(lambda: shutil.rmtree(path, ignore_errors=True))
    return path


@pytest.fixture
def isolated_runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Opt-in isolation for mutable application state used by integration tests."""

    runtime_root = tmp_path / "runtime"
    for name in ("cache", "logs", "artifacts", "data"):
        path = runtime_root / name
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(f"ETF_COCKPIT_{name.upper()}_DIR", str(path))
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("ETF_COCKPIT_OFFLINE", "1")
    monkeypatch.delenv("YAHOO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return runtime_root


@pytest.fixture
def reserved_tcp_port() -> Iterator[socket.socket]:
    """Keep an ephemeral loopback port reserved until fixture teardown."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        yield reservation


# --- Parallel scheduling ----------------------------------------------------------------------
# Files that must share one xdist worker because they use one resource outside their isolated
# project root.  Every entry needs a reason; tests/test_parallel_scheduling.py rejects stale
# entries.  Tests that must not run concurrently with anything use @pytest.mark.serial in the file.
SHARED_RESOURCE_GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {}
_DURATIONS_PATH = Path(__file__).with_name("file_durations.json")


def _scheduling_scope(nodeid: str) -> str:
    path = nodeid.split("::", 1)[0].replace("\\", "/")
    for group, (_reason, files) in SHARED_RESOURCE_GROUPS.items():
        if path in files:
            return f"group:{group}"
    return path


def _file_weights() -> dict[str, float]:
    try:
        payload = json.loads(_DURATIONS_PATH.read_text(encoding="utf-8"))
        return {str(key): float(value) for key, value in payload["files"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not getattr(config.option, "numprocesses", None) and not _XDIST_WORKER:
        return  # serial runs keep pytest's natural order
    # Longest scheduling scopes first (LPT): the heaviest files cannot end up as the tail.  The sort
    # is deterministic, so every worker collects the identical order that xdist requires.
    weights = _file_weights()
    default = sorted(weights.values())[len(weights) // 2] if weights else 1.0  # unknown file: median
    scopes = {item.nodeid: _scheduling_scope(item.nodeid) for item in items}
    paths_by_scope: dict[str, set[str]] = {}
    first_seen: dict[str, int] = {}
    for index, item in enumerate(items):
        paths_by_scope.setdefault(scopes[item.nodeid], set()).add(item.nodeid.split("::", 1)[0].replace("\\", "/"))
        first_seen.setdefault(scopes[item.nodeid], index)
    scope_weight = {scope: sum(weights.get(path, default) for path in paths) for scope, paths in paths_by_scope.items()}
    items.sort(key=lambda item: (-scope_weight[scopes[item.nodeid]], first_seen[scopes[item.nodeid]]))


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_make_scheduler(config: pytest.Config, log: object) -> object | None:
    """With ``--dist loadfile``: keep each file (or shared-resource group) on one worker.

    Module fixtures such as the build_snapshot() templates are then built once per file instead of
    once per worker, and nodeids stay unchanged (unlike ``loadgroup``'s ``@group`` suffix).
    """

    if config.getoption("dist") != "loadfile":
        return None
    from xdist.scheduler import LoadScopeScheduling

    class _FileScopeScheduling(LoadScopeScheduling):
        def _split_scope(self, nodeid: str) -> str:
            return _scheduling_scope(nodeid)

    return _FileScopeScheduling(config, log)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Passing runs leave nothing behind; a failing run keeps its root for inspection until the
    # stale-root pruning of a later session removes it.
    if exitstatus == 0:
        try:
            _remove_isolated_root(ISOLATED_ROOT)
        except OSError as exc:
            print(f"warning: could not remove isolated project root {ISOLATED_ROOT}: {exc}", file=sys.stderr)


# The parallel pilot opts into this exact selected-nodeid evidence.  Do not emit it for ordinary
# test runs.  Manifest emission happens from pytest_collection_finish after marker deselection.


def pytest_collection_finish(session: pytest.Session) -> None:
    """Write the post-deselection pilot manifest when explicitly requested."""

    manifest_value = os.getenv("ETF_COCKPIT_PILOT_NODEID_MANIFEST")
    worker_input = getattr(session.config, "workerinput", None)
    if not manifest_value or (
        worker_input is not None and worker_input.get("workerid") != "gw0"
    ):
        return
    nodeids = [item.nodeid.replace("\\", "/") for item in session.items]
    if len(nodeids) != len(set(nodeids)):
        raise RuntimeError("parallel pilot selected-nodeid manifest contains duplicates")
    destination = Path(manifest_value)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(nodeids, sort_keys=False) + "\n", encoding="utf-8")
