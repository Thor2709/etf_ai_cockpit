"""Validate root-owned local lane observations; never allocate or launch workers.

A lane is an observation, not a distributed lock or a claim of live review.
The root must reconcile all active writers before supplying this manifest.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import unicodedata

SCHEMA = "codex-active-work.v1"
SHA = re.compile(r"[0-9a-f]{40}")
ROOT_FIELDS = {"schema_version", "observed_main", "programme_sha256", "root_session", "all_active_writers_reconciled", "children_in_use", "reviewers_running", "lanes"}
ROOT_ONLY = (".github", ".agents", "issues", "docs/product-completion", "plans",
             "agents.md", "agents.override.md", "plan_step2.md", "readme.md", "changelog.md",
             "docs/development/control_plane.md", "docs/development/work-index.json",
             "docs/codex-config/config-core.toml", "docs/codex-config/global-agents.md",
             "docs/codex-config/agents")
LANE_FIELDS = {"lane_id", "issue", "branch", "worktree", "base", "head", "pr", "writer", "state", "owned_paths", "owned_tests", "runtime_roots", "ports", "resources", "blocker", "next_action"}


def boundary(value: str, *, absolute: bool = False) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or unicodedata.normalize("NFC", value) != value
            or any(c in value for c in "*?[]")):
        raise ValueError("Ambiguous ownership boundary")
    normal = value.replace("\\", "/")
    parts = normal.rstrip("/").split("/")
    if any(part in (".", "..") or part.endswith((" ", ".")) for part in parts if part):
        raise ValueError("Noncanonical ownership boundary")
    if absolute:
        if "" in parts[1:] or ":" in normal[2:] or (":" in normal and not re.match(r"^[A-Za-z]:/", normal)):
            raise ValueError("Noncanonical absolute ownership boundary")
        if normal.startswith("//") or not (PurePosixPath(normal).is_absolute() or PureWindowsPath(normal).is_absolute()):
            raise ValueError("Runtime/worktree boundary must be absolute and local")
        if len([part for part in parts if part]) < 2:
            raise ValueError("Runtime/worktree boundary is too broad")
    elif normal.startswith("/") or ":" in normal or "" in parts:
        raise ValueError("Source boundary must be repository relative")
    return normal.rstrip("/").casefold()


def overlaps(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def conflicts(left: dict, right: dict) -> list[str]:
    reasons = []
    if any(overlaps(a, b) for a in left["paths"] for b in right["paths"]):
        reasons.append("SOURCE_OR_TEST_OWNERSHIP_OVERLAP")
    if overlaps(left["worktree"], right["worktree"]):
        reasons.append("WORKTREE_OVERLAP")
    if any(overlaps(a, b) for a in left["runtime"] for b in right["runtime"]):
        reasons.append("MUTABLE_RUNTIME_OVERLAP")
    if any(overlaps(path, right["worktree"]) for path in left["runtime"]) or any(overlaps(path, left["worktree"]) for path in right["runtime"]):
        reasons.append("RUNTIME_OVERLAPS_OTHER_WORKTREE")
    if set(left["ports"]) & set(right["ports"]):
        reasons.append("PORT_OVERLAP")
    if set(left["resources"]) & set(right["resources"]):
        reasons.append("MUTABLE_RESOURCE_OVERLAP")
    return reasons


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "--no-optional-locks", *args], cwd=root, text=True, stderr=subprocess.PIPE).strip()


def _reject_aliases(path: Path) -> None:
    """Do not mistake textual path disjointness for physical isolation."""
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ValueError("LINKED_OWNERSHIP_OR_RUNTIME_BOUNDARY")
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("REPARSE_OWNERSHIP_OR_RUNTIME_BOUNDARY")


def _local_check(root: Path, lane: dict) -> None:
    worktree = Path(lane["worktree"])
    _reject_aliases(worktree)
    for runtime in lane["runtime_roots"]:
        _reject_aliases(Path(runtime))
    if not worktree.is_absolute() or not worktree.is_dir() or worktree.is_symlink():
        raise ValueError("WORKTREE_NOT_OBSERVED_ON_THIS_MACHINE")
    def common(directory):
        value = Path(_git(directory, "rev-parse", "--git-common-dir"))
        return (directory / value).resolve() if not value.is_absolute() else value.resolve()
    if common(worktree) != common(root):
        raise ValueError("WORKTREE_BELONGS_TO_OTHER_REPOSITORY")
    if Path(_git(worktree, "rev-parse", "--show-toplevel")).resolve() != worktree.resolve():
        raise ValueError("WORKTREE_NOT_EXACT_GIT_ROOT")
    if _git(worktree, "rev-parse", "HEAD") != lane["head"]:
        raise ValueError("LOCAL_HEAD_DRIFT")
    if _git(worktree, "branch", "--show-current") != lane["branch"]:
        raise ValueError("LOCAL_BRANCH_DRIFT")
    subprocess.run(["git", "merge-base", "--is-ancestor", lane["base"], lane["head"]], cwd=worktree, check=True, capture_output=True)
    try:
        from scripts.git_change_paths import changed_paths, working_paths
    except ModuleNotFoundError:
        from git_change_paths import changed_paths, working_paths
    owned = [boundary(path) for path in lane["owned_paths"] + lane["owned_tests"]]
    if any(not any(overlaps(boundary(path), claim) for claim in owned) for path in set(working_paths(worktree)) | set(changed_paths(worktree, lane["base"], lane["head"]))):
        raise ValueError("COMMITTED_OR_WORKING_CHANGES_OUTSIDE_DECLARED_OWNERSHIP")
    for path in lane["owned_paths"] + lane["owned_tests"]:
        target = worktree / path.rstrip("/")
        _reject_aliases(target)
        if not target.resolve().is_relative_to(worktree.resolve()):
            raise ValueError("OWNED_PATH_ESCAPES_WORKTREE")


def validate_lanes(value: object, plan: dict, main: str, programme_hash: str, *, root: Path | None, child_ceiling: int, pulls: dict | None = None) -> dict:
    """Fail closed on incomplete/stale observations; return proposed, not launched waves.

    Tests may omit root for pure schema/conflict fixtures. Such output is never
    admitted as locally verified. A PR lane also needs independently refreshed
    pull metadata; repeating its own claimed head is not a PR readback.
    """
    result = {"status": "UNOBSERVED_NO_PARALLEL_AUTHORITY", "errors": [], "active": [], "parallel_waves": [], "local_verification": root is not None, "apply_authority": False}
    if value is None:
        return result
    try:
        if not isinstance(value, dict) or set(value) != ROOT_FIELDS or value["schema_version"] != SCHEMA:
            raise ValueError("INVALID_ACTIVE_WORK_SCHEMA")
        if value["observed_main"] != main or value["programme_sha256"] != programme_hash:
            raise ValueError("STALE_MAIN_OR_PROGRAMME_IDENTITY")
        if value["all_active_writers_reconciled"] is not True or not isinstance(value["root_session"], str) or not value["root_session"].strip():
            raise ValueError("ACTIVE_WRITER_CENSUS_UNVERIFIED")
        used, reviewers = value["children_in_use"], value["reviewers_running"]
        if type(used) is not int or type(reviewers) is not int or not 0 <= reviewers <= used <= child_ceiling or child_ceiling - used + reviewers < 2:
            raise ValueError("MANDATORY_REVIEW_CAPACITY_NOT_RESERVED")
        if not isinstance(value["lanes"], list):
            raise ValueError("INVALID_LANE_LIST")
        ready = {entry["issue"]: entry for entry in plan["ready"]}
        all_ids = {entry["issue"] for name in ("ready", "blocked", "excluded") for entry in plan[name]}
        normalised, identities, issues = [], set(), set()
        for lane in value["lanes"]:
            if not isinstance(lane, dict) or set(lane) != LANE_FIELDS:
                raise ValueError("MISSING_OR_UNKNOWN_LANE_FIELD")
            key = lane["lane_id"]
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key) or key.casefold() in identities:
                raise ValueError("DUPLICATE_OR_INVALID_LANE_ID")
            identities.add(key.casefold())
            issue = lane["issue"]
            if issue in issues:
                raise ValueError("MULTIPLE_WRITERS_FOR_ONE_ISSUE")
            issues.add(issue)
            root_control = issue is None and lane["writer"] == "codex-root"
            if not root_control and issue not in all_ids:
                raise ValueError(f"{key}: UNKNOWN_OR_ALREADY_INTEGRATED_ISSUE")
            if not root_control and issue not in ready:
                raise ValueError(f"{key}: ISSUE_NOT_READY")
            if lane["writer"] not in {"codex-root", "codex-v2", "agy-staged"}:
                raise ValueError(f"{key}: INDEPENDENT_AGY_OR_UNKNOWN_WRITER_FORBIDDEN")
            if lane["state"] not in {"planned", "active", "frozen", "blocked"}:
                raise ValueError(f"{key}: INVALID_LANE_STATE")
            if not isinstance(lane["branch"], str) or not lane["branch"] or not isinstance(lane["next_action"], str) or not lane["next_action"].strip():
                raise ValueError(f"{key}: MISSING_BRANCH_OR_NEXT_ACTION")
            if lane["base"] != main or not isinstance(lane["head"], str) or not SHA.fullmatch(lane["head"]):
                raise ValueError(f"{key}: STALE_BASE_OR_INVALID_HEAD_REVALIDATE_BEFORE_ADMISSION")
            if not isinstance(lane["blocker"], str) or (lane["state"] == "blocked" and not lane["blocker"].strip()):
                raise ValueError(f"{key}: INVALID_BLOCKER")
            if lane["pr"] is not None:
                if type(lane["pr"]) is not int or lane["pr"] < 1:
                    raise ValueError(f"{key}: INVALID_PR")
                if not isinstance(pulls, dict) or pulls.get("observed_main") != main:
                    raise ValueError(f"{key}: CURRENT_PR_HEAD_NOT_OBSERVED")
                observed = pulls.get("pulls", {}).get(str(lane["pr"]))
                if observed != {"head": lane["head"], "branch": lane["branch"], "base": main, "base_branch": "main", "state": "open"}:
                    raise ValueError(f"{key}: PR_HEAD_BRANCH_OR_STATE_DRIFT")
            for field in ("owned_paths", "owned_tests", "runtime_roots", "ports", "resources"):
                if not isinstance(lane[field], list):
                    raise ValueError(f"{key}: INVALID_{field.upper()}")
            paths = [boundary(path) for path in lane["owned_paths"] + lane["owned_tests"]]
            if not paths or len(paths) != len(set(paths)) or not lane["runtime_roots"]:
                raise ValueError(f"{key}: MISSING_OR_DUPLICATE_SOURCE_TEST_RUNTIME_BOUNDARIES")
            if lane["writer"] != "codex-root" and any(overlaps(path, protected) for path in paths for protected in ROOT_ONLY):
                raise ValueError(f"{key}: ROOT_ONLY_CANONICAL_OR_POLICY_OWNERSHIP")
            if any(not boundary(path).startswith("tests/") and not boundary(path).startswith("docs/codex-config/test_") for path in lane["owned_tests"]):
                raise ValueError(f"{key}: INVALID_TEST_OWNERSHIP")
            worktree = boundary(lane["worktree"], absolute=True)
            runtime = [boundary(path, absolute=True) for path in lane["runtime_roots"]]
            if any(overlaps(path, worktree) and not path.startswith(worktree + "/") for path in runtime):
                raise ValueError(f"{key}: RUNTIME_ROOT_ENCLOSES_WORKTREE")
            if any(type(port) is not int or not 1024 <= port <= 65535 for port in lane["ports"]):
                raise ValueError(f"{key}: INVALID_PORT_RESERVATION")
            if any(not isinstance(resource, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", resource) for resource in lane["resources"]):
                raise ValueError(f"{key}: INVALID_MUTABLE_RESOURCE")
            if root is not None:
                _local_check(root, lane)
            normalised.append({"lane": lane, "paths": paths, "worktree": worktree, "runtime": runtime,
                               "ports": lane["ports"], "resources": [s.casefold() for s in lane["resources"]]})
        normalised.sort(key=lambda item: ready[item["lane"]["issue"]]["rank"] if item["lane"]["issue"] is not None else [-1, 0, 0, 0, 0, item["lane"]["lane_id"]])
        active = [item for item in normalised if item["lane"]["state"] in {"active", "frozen", "blocked"}]
        if sum(item["lane"]["writer"] == "codex-root" for item in normalised) > 1:
            raise ValueError("MULTIPLE_ROOT_INTEGRATION_LANES_FORBIDDEN")
        for i, left in enumerate(active):
            for right in active[i + 1:]:
                reasons = conflicts(left, right)
                if reasons:
                    raise ValueError(f"ACTIVE_LANE_CONFLICT:{left['lane']['lane_id']}:{right['lane']['lane_id']}:" + ",".join(reasons))
        if sum(item["lane"]["writer"] == "codex-v2" for item in active if item["lane"]["state"] == "active") > used - reviewers:
            raise ValueError("ACTIVE_V2_WRITERS_EXCEED_DECLARED_CHILDREN")
        result["active"] = [item["lane"] for item in active]
        available = child_ceiling - used - max(0, 2 - reviewers)
        immediate = list(active)
        waiting = []
        for item in normalised:
            if item in active:
                continue
            if item["lane"]["blocker"] or item["lane"]["state"] == "blocked":
                waiting.append(item)
                continue
            needs_child = item["lane"]["writer"] == "codex-v2"
            if not any(conflicts(item, member) for member in immediate) and (not needs_child or available > 0):
                immediate.append(item)
                available -= int(needs_child)
            else:
                waiting.append(item)
        # Conditional groups are informative only, after reservations/children
        # are released and all identities are observed again.
        later: list[list[dict]] = []
        for item in waiting:
            if item["lane"]["blocker"]:
                continue
            for wave in later:
                if not any(conflicts(item, member) for member in wave) and len(wave) < child_ceiling - 2:
                    wave.append(item)
                    break
            else:
                later.append([item])
        runnable = [item for item in immediate if item["lane"]["state"] not in {"blocked", "frozen"}
                    and not item["lane"]["blocker"]]
        result["parallel_waves"] = [[item["lane"]["lane_id"] for item in runnable]] if runnable else []
        result["reserved_not_runnable"] = [item["lane"]["lane_id"] for item in active if item not in runnable]
        result["conditional_waves"] = [[item["lane"]["lane_id"] for item in wave] for wave in later]
        result["not_admitted_now"] = [item["lane"]["lane_id"] for item in waiting]
        result["status"] = "LOCAL_OBSERVATIONS_VALIDATED_ROOT_ADMISSION_REQUIRED" if root is not None else "SCHEMA_ONLY_NOT_LOCAL_AUTHORITY"
        result["wave_caveat"] = "Later waves require released ownership, fresh main/programme/PR observations and reviewer capacity. No worker is launched. Root serialises every merge and canonical write."
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        result["status"] = "BLOCKED_INVALID_OR_STALE_OWNERSHIP"
        result["errors"] = [str(error)]
        result["parallel_waves"] = []
        result["conditional_waves"] = []
    return result
