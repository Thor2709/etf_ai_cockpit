"""Validate and apply one reviewed post-merge programme-status completion."""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import hashlib
import hmac
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, cast

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

try:
    from scripts import github_mutation_gateway as mutation_gateway
    from scripts import sync_github_issues as sync
    from scripts.issue_registry_core import (
        CONTROL_ALLOWED_TRANSITIONS,
        REGISTRY_PATH,
        control_state_record,
        is_issue0011_legacy_replay_source,
        load_control_state_at,
        validate_control_transition_event,
        validate_status_replay_prefix_shape,
    )
except ModuleNotFoundError:
    import github_mutation_gateway as mutation_gateway
    import sync_github_issues as sync
    from issue_registry_core import (
        CONTROL_ALLOWED_TRANSITIONS,
        REGISTRY_PATH,
        control_state_record,
        is_issue0011_legacy_replay_source,
        load_control_state_at,
        validate_control_transition_event,
        validate_status_replay_prefix_shape,
    )


SCHEMA_VERSION = "etf-ai-cockpit.status-completion-candidate/2.0"
REPLAY_SCHEMA_VERSION = "etf-ai-cockpit.status-replay-candidate/3.0"
DEFAULT_CANDIDATE = Path(".github/issue-transitions/post-merge-control-candidate.json")
ZERO_SUMMARY = {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0}
ONE_UPDATE_SUMMARY = {"create": 0, "update": 1, "close": 0, "reopen": 0, "blocked": 0}
SINGLE_HOP_STATUS_TARGETS = frozenset({"ready", "in_progress", "integrated"})
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
STATUS_RE = re.compile(r"^- Programme status: `([^`]+)`$", re.MULTILINE)
EXPECTED_KEYS = {
    "schema_version",
    "execution_allowed",
    "expected_parent_sha",
    "authority_ref",
    "remote_inventory_sha256",
    "plan_semantic_sha256",
    "expected_update",
}
EXPECTED_UPDATE_KEYS = {"stable_id", "from_status", "to_status"}
REPLAY_KEYS = {
    "stable_id",
    "issue_number",
    "from_status",
    "to_status",
    "reviewed_product_commit",
    "transition_history_prefix",
    "transition_history_append",
    "acceptance_evidence_prefix",
    "acceptance_evidence_append",
}
WORKFLOW_PATH = ".github/workflows/programme-status-completion.yml"
WORKFLOW_NAME = "Programme status completion"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
OIDC_JWKS_URL = f"{OIDC_ISSUER}/.well-known/jwks"
OIDC_MAX_AGE_SECONDS = 60


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _registry_at(root: Path, revision: str) -> dict[str, Any]:
    raw = subprocess.check_output(
        ["git", "show", f"{revision}:{REGISTRY_PATH.as_posix()}"],
        cwd=root,
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("canonical registry at source SHA is malformed")
    return value


def _registry_record(
    registry: dict[str, Any], stable_id: str, *, context: str
) -> dict[str, Any]:
    records = registry.get("records")
    matches = (
        [
            record
            for record in records
            if isinstance(record, dict) and record.get("canonical_id") == stable_id
        ]
        if isinstance(records, list)
        else []
    )
    if len(matches) != 1:
        raise ValueError(f"status replay {context} target is missing or ambiguous")
    return matches[0]


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=root,
            check=False,
        ).returncode
        == 0
    )


def _validate_candidate_blob(
    root: Path,
    *,
    candidate_path: Path,
    candidate_bytes: bytes,
    expected_head: str,
) -> None:
    candidate_relative = DEFAULT_CANDIDATE.as_posix()
    if candidate_path.resolve() != (root / DEFAULT_CANDIDATE).resolve():
        raise ValueError("candidate path must be the canonical status-completion path")
    try:
        expected_blob = _git(root, "rev-parse", f"{expected_head}:{candidate_relative}")
    except subprocess.CalledProcessError as exc:
        raise ValueError("expected head does not contain the candidate path") from exc
    if _git(root, "cat-file", "-t", expected_blob) != "blob":
        raise ValueError("expected head candidate is not a Git blob")
    try:
        _git(root, "ls-files", "--error-unmatch", "--", candidate_relative)
    except subprocess.CalledProcessError as exc:
        raise ValueError("candidate path is not tracked") from exc
    if _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        candidate_relative,
    ):
        raise ValueError("candidate path has staged, unstaged, or untracked changes")
    expected_bytes = subprocess.check_output(
        ["git", "cat-file", "blob", expected_blob],
        cwd=root,
    )
    if candidate_bytes != expected_bytes and candidate_bytes != expected_bytes.replace(
        b"\n", b"\r\n"
    ):
        raise ValueError("checked-out candidate bytes do not match expected head")


def _canonical_candidate_blob_sha256(root: Path, expected_head: str) -> str:
    blob = _git(root, "rev-parse", f"{expected_head}:{DEFAULT_CANDIDATE.as_posix()}")
    return hashlib.sha256(
        subprocess.check_output(["git", "cat-file", "blob", blob], cwd=root)
    ).hexdigest()


def read_actions_run(run_id: str) -> dict[str, Any]:
    value = json.loads(
        mutation_gateway._read_gh(
            ["api", f"repos/{mutation_gateway.REPO}/actions/runs/{run_id}"]
        )
    )
    if not isinstance(value, dict):
        raise ValueError("GitHub Actions run response must be an object")
    return value


def read_check_run(check_run_id: str) -> dict[str, Any]:
    value = json.loads(
        mutation_gateway._read_gh(
            ["api", f"repos/{mutation_gateway.REPO}/check-runs/{check_run_id}"]
        )
    )
    if not isinstance(value, dict):
        raise ValueError("GitHub check run response must be an object")
    return value


def _strict_json(data: bytes, description: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate {description} field")
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed {description}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be an object")
    return value


def _b64url_decode(value: str, description: str) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise ValueError(f"malformed {description}")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, TypeError) as exc:
        raise ValueError(f"malformed {description}") from exc
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise ValueError(f"non-canonical {description}")
    return decoded


def _validate_x5t(value: object, description: str) -> str:
    if not isinstance(value, str) or len(_b64url_decode(value, description)) != 20:
        raise ValueError(f"malformed {description}")
    return value


def _read_url_json(request: urllib.request.Request, description: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            if response.status != 200:
                raise ValueError(f"{description} request failed")
            return _strict_json(response.read(), description)
    except Exception as exc:
        raise ValueError(f"{description} request failed") from exc


def request_actions_oidc_token(audience: str) -> str:
    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if not request_url.startswith("https://") or not request_token:
        raise ValueError("GitHub Actions OIDC request authority is unavailable")
    parsed = urllib.parse.urlsplit(request_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("audience", audience))
    url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )
    response = _read_url_json(
        urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {request_token}"},
            method="GET",
        ),
        "GitHub Actions OIDC token",
    )
    if set(response) != {"value"} or not isinstance(response["value"], str):
        raise ValueError("malformed GitHub Actions OIDC token response")
    return response["value"]


def read_oidc_jwks() -> dict[str, Any]:
    return _read_url_json(
        urllib.request.Request(OIDC_JWKS_URL, method="GET"), "GitHub Actions JWKS"
    )


def _select_jwk(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
    if set(jwks) != {"keys"} or not isinstance(jwks["keys"], list):
        raise ValueError("malformed GitHub Actions JWKS")
    matches = [
        key
        for key in jwks["keys"]
        if isinstance(key, dict) and key.get("kid") == kid
    ]
    if len(matches) > 1:
        raise ValueError("duplicate GitHub Actions signing key")
    return matches[0] if matches else None


def verify_actions_oidc_token(
    token: str,
    *,
    audience: str,
    attestation: dict[str, str],
    live_run: dict[str, Any],
    live_check: dict[str, Any],
    jwks_reader: Callable[[], dict[str, Any]] = read_oidc_jwks,
    now: Callable[[], float] = time.time,
    used_jtis: set[str] | None = None,
) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed GitHub Actions OIDC JWT")
    header = _strict_json(_b64url_decode(parts[0], "JWT header"), "JWT header")
    claims = _strict_json(_b64url_decode(parts[1], "JWT claims"), "JWT claims")
    header_keys = set(header)
    if (
        header_keys not in (
            {"alg", "kid", "typ"},
            {"alg", "kid", "typ", "x5t"},
        )
        or header.get("alg") != "RS256"
        or header.get("typ") != "JWT"
        or not isinstance(header.get("kid"), str)
        or not header["kid"]
    ):
        raise ValueError("unsupported GitHub Actions OIDC JOSE header")
    if "x5t" in header:
        _validate_x5t(header["x5t"], "GitHub Actions OIDC header x5t")
    jwks = jwks_reader()
    jwk = _select_jwk(jwks, header["kid"])
    if jwk is None:
        jwk = _select_jwk(jwks_reader(), header["kid"])
    if jwk is None or set(jwk) - {"kty", "use", "kid", "n", "e", "alg", "x5c", "x5t"}:
        raise ValueError("GitHub Actions OIDC signing key unavailable")
    if (
        jwk.get("kty") != "RSA"
        or jwk.get("use") != "sig"
        or jwk.get("kid") != header["kid"]
        or jwk.get("alg") not in (None, "RS256")
        or not isinstance(jwk.get("n"), str)
        or not isinstance(jwk.get("e"), str)
    ):
        raise ValueError("invalid GitHub Actions OIDC signing key")
    if "x5t" in jwk:
        _validate_x5t(jwk["x5t"], "GitHub Actions OIDC JWK x5t")
    if (
        "x5t" in header
        and "x5t" in jwk
        and not hmac.compare_digest(header["x5t"], jwk["x5t"])
    ):
        raise ValueError("invalid GitHub Actions OIDC signing key")
    public_key = rsa.RSAPublicNumbers(
        int.from_bytes(_b64url_decode(jwk["e"], "JWK exponent"), "big"),
        int.from_bytes(_b64url_decode(jwk["n"], "JWK modulus"), "big"),
    ).public_key()
    try:
        public_key.verify(
            _b64url_decode(parts[2], "JWT signature"),
            f"{parts[0]}.{parts[1]}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception as exc:
        raise ValueError("invalid GitHub Actions OIDC signature") from exc
    required_strings = {
        "iss", "sub", "aud", "jti", "repository", "repository_id", "event_name",
        "ref", "sha", "workflow_ref", "workflow_sha", "run_id", "run_number",
        "run_attempt", "runner_environment", "check_run_id",
    }
    if any(not isinstance(claims.get(key), str) or not claims[key] for key in required_strings):
        raise ValueError("missing or invalid GitHub Actions OIDC claim")
    if any(type(claims.get(key)) is not int for key in ("iat", "nbf", "exp")):
        raise ValueError("missing or invalid GitHub Actions OIDC time claim")
    current = int(now())
    if not (current - OIDC_MAX_AGE_SECONDS <= claims["iat"] <= current + 5):
        raise ValueError("GitHub Actions OIDC proof is not fresh")
    if claims["nbf"] > current + 5 or claims["exp"] <= current or claims["exp"] <= claims["iat"]:
        raise ValueError("GitHub Actions OIDC proof is outside its validity window")
    if used_jtis is not None:
        if claims["jti"] in used_jtis:
            raise ValueError("GitHub Actions OIDC proof was replayed")
        used_jtis.add(claims["jti"])
    repository = live_run.get("repository")
    repository_id = str(repository.get("id", "")) if isinstance(repository, dict) else ""
    expected = {
        "iss": OIDC_ISSUER,
        "aud": audience,
        "sub": f"repo:{mutation_gateway.REPO}:ref:refs/heads/main",
        "repository": mutation_gateway.REPO,
        "repository_id": repository_id,
        "event_name": "push",
        "ref": "refs/heads/main",
        "sha": attestation["event_after"],
        "workflow_ref": attestation["workflow_ref"],
        "workflow_sha": attestation["event_after"],
        "run_id": attestation["run_id"],
        "run_number": attestation["run_number"],
        "run_attempt": "1",
        "runner_environment": "github-hosted",
        "check_run_id": str(live_check.get("id", "")),
    }
    if not repository_id or any(claims.get(key) != value for key, value in expected.items()):
        raise ValueError("GitHub Actions OIDC caller binding mismatch")
    return claims


def validate_live_actions_run(
    attestation: dict[str, str],
    run_reader: Callable[[str], dict[str, Any]],
) -> None:
    """Require the actual, still-active first run for the introducing push."""

    try:
        run = run_reader(attestation["run_id"])
    except Exception as exc:
        raise mutation_gateway.MutationPolicyError(
            "github_actions_run_unverifiable",
            mutation_gateway._policy_evidence("github_actions_run_unverifiable"),
        ) from exc
    repository = run.get("repository")
    if (
        str(run.get("id", "")) != attestation["run_id"]
        or not isinstance(repository, dict)
        or repository.get("full_name") != mutation_gateway.REPO
        or not str(repository.get("id", "")).isdigit()
        or run.get("path") != WORKFLOW_PATH
        or run.get("name") != WORKFLOW_NAME
        or run.get("event") != "push"
        or run.get("head_branch") != "main"
        or run.get("head_sha") != attestation["event_after"]
        or str(run.get("run_number", "")) != attestation["run_number"]
        or str(run.get("run_attempt", "")) != "1"
        or run.get("status") != "in_progress"
    ):
        raise mutation_gateway.MutationPolicyError(
            "github_actions_run_attestation_mismatch",
            mutation_gateway._policy_evidence(
                "github_actions_run_attestation_mismatch"
            ),
        )


def validate_live_check_run(
    attestation: dict[str, str],
    check_run_id: str,
    check_reader: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    try:
        check = check_reader(check_run_id)
    except Exception as exc:
        raise mutation_gateway.MutationPolicyError(
            "github_check_run_unverifiable",
            mutation_gateway._policy_evidence("github_check_run_unverifiable"),
        ) from exc
    app = check.get("app")
    details_url = str(check.get("details_url", ""))
    expected_prefix = (
        f"https://github.com/{mutation_gateway.REPO}/actions/runs/"
        f"{attestation['run_id']}/job/"
    )
    if (
        str(check.get("id", "")) != check_run_id
        or check.get("head_sha") != attestation["event_after"]
        or check.get("status") != "in_progress"
        or not isinstance(app, dict)
        or app.get("slug") != "github-actions"
        or not details_url.startswith(expected_prefix)
        or not details_url[len(expected_prefix) :].isdigit()
    ):
        raise mutation_gateway.MutationPolicyError(
            "github_check_run_attestation_mismatch",
            mutation_gateway._policy_evidence("github_check_run_attestation_mismatch"),
        )
    return check


def verify_fresh_caller_proof(
    attestation: dict[str, str],
    *,
    run_reader: Callable[[str], dict[str, Any]],
    check_reader: Callable[[str], dict[str, Any]],
    token_requester: Callable[[str], str],
    jwks_reader: Callable[[], dict[str, Any]],
    used_jtis: set[str],
    now: Callable[[], float] = time.time,
) -> None:
    try:
        credential = os.environ.get("GH_TOKEN")
        if credential is None or not credential:
            raise ValueError("GitHub issue credential is unavailable")
        audience = hashlib.sha256(credential.encode("utf-8")).hexdigest()
        token = token_requester(audience)
        # The unverified claim is used only to locate the check that the signed
        # token must subsequently bind; it grants no authority by itself.
        token_parts = token.split(".")
        if len(token_parts) != 3:
            raise ValueError("malformed GitHub Actions OIDC JWT")
        unverified = _strict_json(
            _b64url_decode(token_parts[1], "JWT claims"), "JWT claims"
        )
        check_run_id = unverified.get("check_run_id")
        if not isinstance(check_run_id, str) or not check_run_id.isdigit():
            raise ValueError("invalid GitHub Actions OIDC check_run_id")
        live_run = run_reader(attestation["run_id"])
        validate_live_actions_run(attestation, lambda _run_id: live_run)
        live_check = validate_live_check_run(attestation, check_run_id, check_reader)
        verify_actions_oidc_token(
            token,
            audience=audience,
            attestation=attestation,
            live_run=live_run,
            live_check=live_check,
            jwks_reader=jwks_reader,
            now=now,
            used_jtis=used_jtis,
        )
    except mutation_gateway.MutationPolicyError:
        raise
    except Exception as exc:
        raise mutation_gateway.MutationPolicyError(
            "github_actions_oidc_caller_proof_invalid",
            mutation_gateway._policy_evidence(
                "github_actions_oidc_caller_proof_invalid"
            ),
        ) from exc


def fetch_origin_main(root: Path) -> None:
    subprocess.run(
        ["git", "fetch", "--no-tags", "origin", "main"],
        cwd=root,
        check=True,
    )


def github_actions_push_attestation(
    run_reader: Callable[[str], dict[str, Any]] = read_actions_run,
) -> dict[str, str]:
    """Read, cross-check and attest the native introducing GitHub push run."""

    required = {
        key: os.environ.get(key, "")
        for key in (
            "GITHUB_ACTIONS",
            "GITHUB_EVENT_NAME",
            "GITHUB_REF",
            "GITHUB_SHA",
            "GITHUB_RUN_ATTEMPT",
            "GITHUB_RUN_ID",
            "GITHUB_RUN_NUMBER",
            "GITHUB_WORKFLOW_REF",
            "GITHUB_REPOSITORY",
            "GITHUB_ACTOR",
            "GITHUB_EVENT_PATH",
        )
    }
    event_path = Path(required["GITHUB_EVENT_PATH"])
    if required["GITHUB_ACTIONS"] != "true" or not event_path.is_file():
        raise mutation_gateway.MutationPolicyError(
            "github_actions_apply_required",
            mutation_gateway._policy_evidence("github_actions_apply_required"),
        )
    event_bytes = event_path.read_bytes()
    try:
        event = json.loads(event_bytes)
    except json.JSONDecodeError as exc:
        raise mutation_gateway.MutationPolicyError(
            "invalid_github_push_event",
            mutation_gateway._policy_evidence("invalid_github_push_event"),
        ) from exc
    repository = event.get("repository") if isinstance(event, dict) else None
    pusher = event.get("pusher") if isinstance(event, dict) else None
    head_commit = event.get("head_commit") if isinstance(event, dict) else None
    attestation = {
        "event_name": required["GITHUB_EVENT_NAME"],
        "event_ref": required["GITHUB_REF"],
        "run_attempt": required["GITHUB_RUN_ATTEMPT"],
        "event_before": str(event.get("before", "")),
        "event_after": str(event.get("after", "")),
        "actor": required["GITHUB_ACTOR"],
        "pusher": str(pusher.get("name", "")) if isinstance(pusher, dict) else "",
        "run_id": required["GITHUB_RUN_ID"],
        "run_number": required["GITHUB_RUN_NUMBER"],
        "workflow_ref": required["GITHUB_WORKFLOW_REF"],
        "repository": required["GITHUB_REPOSITORY"],
        "event_payload_sha256": hashlib.sha256(event_bytes).hexdigest(),
    }
    try:
        mutation_gateway._validate_run_attestation(
            {
                key: attestation[key]
                for key in (
                    "run_id",
                    "run_number",
                    "workflow_ref",
                    "repository",
                    "event_payload_sha256",
                )
            }
        )
    except ValueError as exc:
        raise mutation_gateway.MutationPolicyError(
            "invalid_github_actions_run_attestation",
            mutation_gateway._policy_evidence(
                "invalid_github_actions_run_attestation"
            ),
        ) from exc
    if (
        attestation["event_name"] != "push"
        or attestation["event_ref"] != "refs/heads/main"
        or attestation["run_attempt"] != "1"
        or attestation["event_after"] != required["GITHUB_SHA"]
        or not SHA_RE.fullmatch(attestation["event_before"])
        or not SHA_RE.fullmatch(attestation["event_after"])
        or not attestation["actor"]
        or not attestation["pusher"]
        or not isinstance(repository, dict)
        or repository.get("full_name") != mutation_gateway.REPO
        or event.get("ref") != "refs/heads/main"
        or not isinstance(head_commit, dict)
        or head_commit.get("id") != attestation["event_after"]
    ):
        raise mutation_gateway.MutationPolicyError(
            "ineligible_authority_gateway_event",
            mutation_gateway._policy_evidence(
                "ineligible_authority_gateway_event"
            ),
        )
    validate_live_actions_run(attestation, run_reader)
    return attestation


def revalidate_live_authority(
    root: Path,
    *,
    expected_parent: str,
    expected_head: str,
    main_ref: str | None,
    attestation: dict[str, str],
    run_reader: Callable[[str], dict[str, Any]],
    main_fetcher: Callable[[Path], None],
    caller_proof_verifier: Callable[[], None],
) -> None:
    """Refresh live read authorities immediately before one GitHub POST."""

    main_fetcher(root)
    caller_proof_verifier()
    mutation_gateway.validate_authority_git_transition(
        root,
        event_before=expected_parent,
        event_after=expected_head,
        main_ref=main_ref,
    )


def load_candidate(candidate_bytes: bytes) -> dict[str, Any]:
    payload = json.loads(candidate_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("status-completion candidate must be a JSON object")
    return payload


def validate_git_bindings(
    root: Path,
    candidate: dict[str, Any],
    *,
    candidate_path: Path,
    candidate_bytes: bytes,
    expected_parent: str,
    expected_head: str,
    main_ref: str | None,
) -> None:
    if not SHA_RE.fullmatch(expected_parent) or not SHA_RE.fullmatch(expected_head):
        raise ValueError("expected parent and head must be full commit SHAs")
    if candidate.get("expected_parent_sha") != expected_parent:
        raise ValueError("candidate expected parent/base SHA mismatch")
    checked_head = _git(root, "rev-parse", "HEAD")
    _validate_candidate_blob(
        root,
        candidate_path=candidate_path,
        candidate_bytes=candidate_bytes,
        expected_head=expected_head,
    )
    if main_ref is None:
        if not _is_ancestor(root, expected_parent, expected_head):
            raise ValueError(
                "candidate expected parent/base is not an ancestor of head"
            )
        if checked_head != expected_head and not _is_ancestor(
            root, expected_head, checked_head
        ):
            raise ValueError(
                "expected head is not the checked-out validation commit or its ancestor"
            )
    else:
        if checked_head != expected_head:
            raise ValueError("status-completion head does not equal checked-out HEAD")
        if not _is_ancestor(root, expected_parent, expected_head):
            raise ValueError(
                "candidate expected parent/base is not an ancestor of head"
            )
        current_main = _git(root, "rev-parse", main_ref)
        if not _is_ancestor(root, expected_head, current_main):
            raise ValueError("status-completion trigger head is not on current main")
        changed = _git(
            root,
            "diff",
            "--name-only",
            expected_head,
            current_main,
            "--",
            DEFAULT_CANDIDATE.as_posix(),
            REGISTRY_PATH.as_posix(),
        )
        if changed:
            raise ValueError("status-completion authority was superseded on current main")


def _programme_status(body: str) -> str:
    matches = STATUS_RE.findall(body)
    if len(matches) != 1:
        raise ValueError("remote issue has ambiguous programme status")
    return matches[0]


def validate_single_hop_status_transition(from_status: object, to_status: object) -> None:
    """Validate the one status-only forward hop shared by prepare and apply."""

    if not isinstance(from_status, str) or not isinstance(to_status, str):
        raise ValueError("candidate status transition is malformed")
    if to_status not in SINGLE_HOP_STATUS_TARGETS:
        raise ValueError("candidate status transition targets an unrelated status")
    if to_status not in CONTROL_ALLOWED_TRANSITIONS.get(from_status, frozenset()):
        raise ValueError("candidate status transition is not a canonical direct transition")


def _accepted_remote_status_projection(issue: dict[str, Any]) -> tuple[dict[str, Any], str]:
    normalised = sync.normalise_remote_issue(issue)
    projection = normalised.get("status_projection")
    if not isinstance(projection, dict) or projection.get("accepted") is not True:
        raise ValueError("candidate remote status projection is malformed or unaccepted")
    status = projection.get("status")
    if not isinstance(status, str) or not status:
        raise ValueError("candidate remote status projection status is malformed")
    return normalised, status


def project_status_replay_record(
    source_record: dict[str, Any],
    history_append: list[dict[str, Any]],
    evidence_append: list[dict[str, Any]],
    *,
    stable_id: str | None = None,
) -> dict[str, Any]:
    """Return the exact canonical record produced by the bounded replay."""

    stable_id = stable_id or str(source_record.get("canonical_id", ""))
    if source_record.get("programme_status") != "in_progress":
        raise ValueError("status replay source status is not in_progress")
    if len(history_append) != 2 or len(evidence_append) != 2:
        raise ValueError("status replay projection requires exactly two appends")
    expected = deepcopy(source_record)
    for index, event in enumerate(history_append):
        validate_control_transition_event(stable_id, expected, event)
        expected["programme_status"] = event["to"]
        expected["verified_commit"] = event["verified_commit"]
        expected["verified_date"] = event["reviewed_date"]
        expected["status_transition"] = {
            "from": event["from"],
            "to": event["to"],
            "review_reference": event["review_reference"],
        }
        expected.setdefault("transition_history", []).append(deepcopy(event))
        expected.setdefault("acceptance_evidence", []).append(
            deepcopy(evidence_append[index])
        )
    return expected


def _validate_status_replay_candidate(
    candidate: dict[str, Any],
    plan: dict[str, Any],
    remote: list[dict[str, Any]],
    *,
    source_record: dict[str, Any] | None = None,
    current_record: dict[str, Any] | None = None,
) -> None:
    if set(candidate) != {
        "schema_version",
        "execution_allowed",
        "expected_parent_sha",
        "authority_ref",
        "remote_inventory_sha256",
        "plan_semantic_sha256",
        "expected_replay",
    }:
        raise ValueError("status replay candidate envelope fields are not narrowly bounded")
    if candidate.get("schema_version") != REPLAY_SCHEMA_VERSION:
        raise ValueError("status replay candidate schema version mismatch")
    if candidate.get("execution_allowed") is not False:
        raise ValueError("candidate must preserve execution_allowed=false")
    if not SHA_RE.fullmatch(str(candidate.get("expected_parent_sha", ""))):
        raise ValueError("candidate expected parent/base SHA is invalid")
    if not HASH_RE.fullmatch(str(candidate.get("authority_ref", ""))):
        raise ValueError("candidate authority reference is invalid")
    if candidate.get("remote_inventory_sha256") != plan.get("remote_inventory_sha256"):
        raise ValueError("candidate remote inventory SHA mismatch")
    if candidate.get("plan_semantic_sha256") != plan.get("plan_sha256"):
        raise ValueError("candidate semantic plan SHA mismatch")
    replay = candidate.get("expected_replay")
    if not isinstance(replay, dict) or set(replay) != REPLAY_KEYS:
        raise ValueError("status replay candidate contract fields are malformed")
    stable_id = str(replay.get("stable_id", ""))
    if not sync.MARKER_RE.fullmatch(f"<!-- etf-ai-cockpit:stable-id={stable_id} -->"):
        raise ValueError("status replay candidate stable ID is invalid")
    if not isinstance(replay.get("issue_number"), int) or replay["issue_number"] <= 0:
        raise ValueError("status replay candidate issue number is invalid")
    if replay.get("from_status") != "in_progress" or replay.get("to_status") != "integrated":
        raise ValueError("status replay candidate must cover in_progress to integrated")
    reviewed_commit = str(replay.get("reviewed_product_commit", ""))
    if not SHA_RE.fullmatch(reviewed_commit):
        raise ValueError("status replay reviewed product commit is invalid")
    history_prefix = replay.get("transition_history_prefix")
    history_append = replay.get("transition_history_append")
    evidence_prefix = replay.get("acceptance_evidence_prefix")
    evidence_append = replay.get("acceptance_evidence_append")
    if not all(isinstance(value, list) for value in (history_prefix, history_append, evidence_prefix, evidence_append)):
        raise ValueError("status replay canonical append data is malformed")
    history_prefix = cast(list[dict[str, Any]], history_prefix)
    history_append = cast(list[dict[str, Any]], history_append)
    evidence_prefix = cast(list[dict[str, Any]], evidence_prefix)
    evidence_append = cast(list[dict[str, Any]], evidence_append)
    legacy_bootstrap = is_issue0011_legacy_replay_source(stable_id, source_record)
    validate_status_replay_prefix_shape(
        stable_id,
        history_prefix,
        evidence_prefix,
        programme_status=replay.get("from_status"),
        dependency_edge_evidence=(
            source_record.get("dependency_edge_evidence")
            if isinstance(source_record, dict)
            else None
        ),
        verified_commit=(source_record.get("verified_commit") if isinstance(source_record, dict) else None),
        verified_date=(source_record.get("verified_date") if isinstance(source_record, dict) else None),
        status_transition=(source_record.get("status_transition") if isinstance(source_record, dict) else None),
        allow_legacy_bootstrap_origin=legacy_bootstrap,
    )
    if len(history_append) != 2 or len(evidence_append) != 2:
        raise ValueError("status replay requires exactly two matching appended entries")
    mutation_gateway._validate_replay_hops(
        history_append, reviewed_product_commit=reviewed_commit
    )
    expected_hops = (("in_progress", "implemented_initially"), ("implemented_initially", "integrated"))
    if any(
        not isinstance(event, dict)
        or event.get("from") != expected_hops[index][0]
        or event.get("to") != expected_hops[index][1]
        or event.get("event_type") == "dependency_edge_update"
        or "dependency_edge" in event
        for index, event in enumerate(history_append)
    ):
        raise ValueError("status replay hops are missing, reversed, duplicated, or unsafe")
    evidence_keys = {
        "status",
        "evidence_references",
        "review_reference",
        "reviewer",
        "reviewed_date",
    }
    for index, evidence in enumerate(evidence_append):
        if not isinstance(evidence, dict) or set(evidence) != evidence_keys:
            raise ValueError("status replay acceptance evidence is malformed")
        if evidence.get("status") != expected_hops[index][1]:
            raise ValueError("status replay acceptance evidence does not match its hop")
        event = history_append[index]
        if any(
            evidence.get(key) != event.get(key)
            for key in ("evidence_references", "review_reference", "reviewer", "reviewed_date")
        ):
            raise ValueError("status replay review evidence is not bound to its hop")
        if event.get("verified_commit") != reviewed_commit:
            raise ValueError("status replay hops must share one reviewed product commit")
    review_keys = (
        "review_reference",
        "evidence_references",
        "reviewer",
        "reviewed_date",
    )
    if any(
        history_append[0].get(key) != history_append[1].get(key)
        for key in review_keys
    ):
        raise ValueError("status replay hops must share identical review evidence")
    if not isinstance(source_record, dict) or not isinstance(current_record, dict):
        raise ValueError("status replay source and current canonical records are required")
    if not stable_id or not isinstance(source_record, dict) or not isinstance(current_record, dict):
        raise ValueError("status replay canonical issue identity mismatch")
    source_history = source_record.get("transition_history")
    source_evidence = source_record.get("acceptance_evidence")
    current_history = current_record.get("transition_history")
    current_evidence = current_record.get("acceptance_evidence")
    validate_status_replay_prefix_shape(
        stable_id,
        source_history,
        source_evidence,
        programme_status=source_record.get("programme_status"),
        dependency_edge_evidence=source_record.get("dependency_edge_evidence"),
        verified_commit=source_record.get("verified_commit"),
        verified_date=source_record.get("verified_date"),
        status_transition=source_record.get("status_transition"),
        allow_legacy_bootstrap_origin=legacy_bootstrap,
    )
    if legacy_bootstrap:
        source_history = []
    validate_status_replay_prefix_shape(
        stable_id,
        current_history,
        current_evidence,
        programme_status=current_record.get("programme_status"),
        dependency_edge_evidence=current_record.get("dependency_edge_evidence"),
        verified_commit=current_record.get("verified_commit"),
        verified_date=current_record.get("verified_date"),
        status_transition=current_record.get("status_transition"),
        allow_legacy_bootstrap_origin=legacy_bootstrap,
    )
    if (
        source_record.get("programme_status") != "in_progress"
        or not isinstance(source_history, list)
        or not isinstance(source_evidence, list)
        or history_prefix != source_history
        or evidence_prefix != source_evidence
    ):
        raise ValueError("status replay prefixes do not equal the source record")
    if (
        not isinstance(current_history, list)
        or not isinstance(current_evidence, list)
        or current_history != source_history + history_append
        or current_evidence != source_evidence + evidence_append
    ):
        raise ValueError("status replay current record is not exactly two source-bound appends")
    expected = project_status_replay_record(
        source_record, history_append, evidence_append, stable_id=stable_id
    )
    if expected != current_record:
        raise ValueError("status replay canonical projection differs from source-bound replay")

    summary = plan.get("summary")
    if summary != {"create": 0, "update": 1, "close": 0, "reopen": 0, "blocked": 0}:
        raise ValueError("status replay plan is not exactly one update")
    actions = plan.get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        raise ValueError("status replay plan must contain exactly one action")
    action = actions[0]
    if (
        action.get("kind") != "update"
        or action.get("stable_id") != stable_id
        or action.get("programme_status") != "integrated"
    ):
        raise ValueError("status replay plan update is not the target integrated status")
    normalised = [sync.normalise_remote_issue(issue) for issue in remote]
    matching = [
        issue
        for issue in normalised
        if stable_id in set(sync.MARKER_RE.findall(issue["body"]))
    ]
    if len(matching) != 1 or matching[0]["number"] != action.get("remote_number"):
        raise ValueError("status replay remote issue identity is ambiguous")
    if action.get("title") != matching[0]["title"]:
        raise ValueError("status replay plan changes the remote issue title")
    if replay["issue_number"] != matching[0]["number"]:
        raise ValueError("status replay candidate issue number does not match remote")
    projection = matching[0].get("status_projection")
    if (
        not isinstance(projection, dict)
        or projection.get("accepted") is not True
        or projection.get("status") != "in_progress"
    ):
        raise ValueError("status replay candidate source does not match accepted remote projection")
    evidence = sync.safe_plan_evidence(plan, normalised)
    if evidence["actions"][0].get("managed_field_deltas") != ["Programme status"]:
        raise ValueError("status replay plan contains a non-status delta")


def validate_candidate(
    candidate: dict[str, Any],
    plan: dict[str, Any],
    remote: list[dict[str, Any]],
    *,
    source_record: dict[str, Any] | None = None,
    current_record: dict[str, Any] | None = None,
) -> None:
    if candidate.get("schema_version") == REPLAY_SCHEMA_VERSION:
        _validate_status_replay_candidate(
            candidate,
            plan,
            remote,
            source_record=source_record,
            current_record=current_record,
        )
        return
    if set(candidate) != EXPECTED_KEYS:
        raise ValueError("candidate envelope fields are not narrowly bounded")
    if candidate.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("candidate schema version mismatch")
    if candidate.get("execution_allowed") is not False:
        raise ValueError("candidate must preserve execution_allowed=false")
    if not SHA_RE.fullmatch(str(candidate.get("expected_parent_sha", ""))):
        raise ValueError("candidate expected parent/base SHA is invalid")
    if not HASH_RE.fullmatch(str(candidate.get("authority_ref", ""))):
        raise ValueError("candidate authority reference is invalid")
    inventory = str(candidate.get("remote_inventory_sha256", ""))
    semantic = str(candidate.get("plan_semantic_sha256", ""))
    if not HASH_RE.fullmatch(inventory) or inventory != plan.get(
        "remote_inventory_sha256"
    ):
        raise ValueError("candidate remote inventory SHA mismatch")
    if not HASH_RE.fullmatch(semantic) or semantic != plan.get("plan_sha256"):
        raise ValueError("candidate semantic plan SHA mismatch")

    expected = candidate.get("expected_update")
    if not isinstance(expected, dict) or set(expected) != EXPECTED_UPDATE_KEYS:
        raise ValueError("candidate expected update is not narrowly bounded")
    stable_id = str(expected.get("stable_id", ""))
    if not sync.MARKER_RE.fullmatch(f"<!-- etf-ai-cockpit:stable-id={stable_id} -->"):
        raise ValueError("candidate stable ID is invalid")
    from_status = str(expected.get("from_status", ""))
    to_status = expected.get("to_status")
    validate_single_hop_status_transition(from_status, to_status)

    summary = plan.get("summary")
    if summary != ONE_UPDATE_SUMMARY:
        raise ValueError("current plan is not exactly one update")
    actions = plan.get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        raise ValueError("current plan must contain exactly one action")
    action = actions[0]
    if (
        not isinstance(action, dict)
        or action.get("kind") != "update"
        or action.get("stable_id") != stable_id
        or action.get("programme_status") != to_status
        or action.get("desired_state") != "open"
    ):
        raise ValueError("current plan update does not match candidate stable ID")

    normalised = [sync.normalise_remote_issue(issue) for issue in remote]
    matching = [
        issue
        for issue in normalised
        if stable_id in set(sync.MARKER_RE.findall(issue["body"]))
    ]
    if len(matching) != 1 or matching[0]["number"] != action.get("remote_number"):
        raise ValueError("candidate remote issue identity is ambiguous")
    if action.get("title") != matching[0]["title"]:
        raise ValueError("current plan contains a non-status delta")
    projection = matching[0].get("status_projection")
    if (
        not isinstance(projection, dict)
        or projection.get("accepted") is not True
        or projection.get("status") != from_status
        or matching[0].get("state") != "open"
    ):
        raise ValueError("candidate from status does not match accepted remote projection")
    evidence = sync.safe_plan_evidence(plan, normalised)
    if evidence["actions"][0].get("managed_field_deltas") != ["Programme status"]:
        raise ValueError("current plan contains a non-status delta")


def run(
    root: Path,
    candidate_path: Path,
    *,
    expected_parent: str,
    expected_head: str,
    main_ref: str | None,
    apply: bool,
    evidence_out: Path | None = None,
    remote_reader: Callable[[], list[dict[str, Any]]] = sync.gh_list_issues,
    mutation_transport: mutation_gateway.MutationTransport | None = None,
    event_name: str | None = None,
    event_ref: str | None = None,
    run_attempt: str | None = None,
    event_before: str | None = None,
    event_after: str | None = None,
    actor: str | None = None,
    pusher: str | None = None,
    run_id: str | None = None,
    run_number: str | None = None,
    workflow_ref: str | None = None,
    repository: str | None = None,
    event_payload_sha256: str | None = None,
    actions_run_reader: Callable[[str], dict[str, Any]] = read_actions_run,
    main_fetcher: Callable[[Path], None] = fetch_origin_main,
    caller_proof_verifier: Callable[[], None] | None = None,
) -> None:
    evidence: dict[str, Any] = {
        "schema_version": "etf-ai-cockpit.status-completion-evidence/1.0",
        "execution_allowed": False,
        "mode": "apply" if apply else "validate",
        "expected_parent_sha": expected_parent,
        "expected_head_sha": expected_head,
        "terminal_status": "failed",
        "zero_action_readback": None,
    }
    try:
        if not apply and not event_before and not event_after:
            event_name = "push"
            event_ref = "refs/heads/main"
            run_attempt = "1"
            event_before = expected_parent
            event_after = expected_head
            actor = "offline-validator"
            pusher = "offline-validator"
            run_id = "1"
            run_number = "1"
            workflow_ref = (
                f"{mutation_gateway.REPO}/.github/workflows/"
                "programme-status-completion.yml@refs/heads/main"
            )
            repository = mutation_gateway.REPO
            event_payload_sha256 = "0" * 64

        if (
            event_name != "push"
            or event_ref != "refs/heads/main"
            or run_attempt != "1"
            or event_before != expected_parent
            or event_after != expected_head
            or not actor
            or not pusher
            or not run_id
            or not run_number
            or not workflow_ref
            or not repository
            or not event_payload_sha256
        ):
            raise mutation_gateway.MutationPolicyError(
                "ineligible_authority_gateway_event",
                mutation_gateway._policy_evidence(
                    "ineligible_authority_gateway_event"
                ),
            )
        attestation = {
            "event_name": str(event_name),
            "event_ref": str(event_ref),
            "run_attempt": str(run_attempt),
            "event_before": str(event_before),
            "event_after": str(event_after),
            "actor": str(actor),
            "pusher": str(pusher),
            "run_id": str(run_id),
            "run_number": str(run_number),
            "workflow_ref": str(workflow_ref),
            "repository": str(repository),
            "event_payload_sha256": str(event_payload_sha256),
        }
        if apply:
            if caller_proof_verifier is None:
                raise mutation_gateway.MutationPolicyError(
                    "github_actions_oidc_caller_proof_required",
                    mutation_gateway._policy_evidence(
                        "github_actions_oidc_caller_proof_required"
                    ),
                )
            caller_proof_verifier()
        proof_revalidator = caller_proof_verifier
        prior_records, records, git_binding = (
            mutation_gateway.validate_authority_git_transition(
                root,
                event_before=expected_parent,
                event_after=expected_head,
                main_ref=main_ref,
            )
        )
        authority = records[-1]
        evidence["authority"] = git_binding
        registry = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
        remote = remote_reader()
        map_path = root / sync.DEFAULT_MAP_PATH
        historical_map = (
            json.loads(map_path.read_text(encoding="utf-8"))
            if map_path.exists()
            else None
        )
        if prior_records:
            prior_reconciliation = mutation_gateway.reconcile_authority_ledger(
                prior_records, remote, root=root
            )
            if not prior_reconciliation.get("accepted"):
                raise ValueError(
                    "predecessor authority reconciliation failed: "
                    + str(prior_reconciliation.get("error"))
                )
        if authority["authority_type"] == "legacy_bootstrap":
            reconciliation = mutation_gateway.reconcile_authority_ledger(
                records, remote, root=None
            )
            if not reconciliation.get("accepted"):
                raise ValueError(
                    "legacy bootstrap reconciliation failed: "
                    + str(reconciliation.get("error"))
                )
            evidence["terminal_status"] = "bootstrap_validated"
            evidence["zero_action_readback"] = True
            print("VALIDATED_GITHUB_MUTATION_AUTHORITY_BOOTSTRAP")
            return

        plan = sync.plan_actions(
            registry,
            remote,
            historical_map=historical_map,
            authority_records=prior_records,
            authority_root=root,
        )
        payload = authority["payload"]
        if authority["authority_type"] == "status":
            candidate_bytes = candidate_path.read_bytes()
            candidate = load_candidate(candidate_bytes)
            validate_git_bindings(
                root,
                candidate,
                candidate_path=candidate_path,
                candidate_bytes=candidate_bytes,
                expected_parent=expected_parent,
                expected_head=expected_head,
                main_ref=main_ref,
            )
            validate_candidate(candidate, plan, remote)
            candidate_oid = _git(
                root,
                "rev-parse",
                f"{expected_head}:{DEFAULT_CANDIDATE.as_posix()}",
            )
            candidate_sha256 = _canonical_candidate_blob_sha256(root, expected_head)
            if (
                candidate.get("authority_ref") != payload["candidate_authority_ref"]
                or payload["candidate_authority_ref"]
                != mutation_gateway.candidate_authority_ref(payload)
                or payload["candidate_blob_oid"] != candidate_oid
                or payload["candidate_blob_sha256"] != candidate_sha256
                or payload["plan_sha256"] != candidate["plan_semantic_sha256"]
            ):
                raise ValueError("candidate does not bind the committed authority")
            expected_update = candidate["expected_update"]
            stable_id = str(expected_update["stable_id"])
            reviewed_matches = [
                issue
                for issue in remote
                if int(issue.get("number", 0)) == payload["issue_number"]
                and str(issue.get("id", "")) == payload["database_id"]
                and str(issue.get("node_id") or issue.get("nodeId") or "")
                == payload["node_id"]
            ]
            if len(reviewed_matches) != 1:
                raise ValueError("authority target issue identity mismatch")
            projection = mutation_gateway.project_status_events(reviewed_matches[0])
            evidence.update(
                {
                    "remote_inventory_sha256": candidate.get(
                        "remote_inventory_sha256"
                    ),
                    "plan_semantic_sha256": candidate.get("plan_semantic_sha256"),
                    "authority_ref": candidate.get("authority_ref"),
                    "expected_update": expected_update,
                    "candidate_blob_sha256": candidate_sha256,
                    "action_scope": sync.safe_plan_evidence(plan, remote)["actions"],
                    "mutation": {
                        "transport": "github_issue_comment_append",
                        "authority_id": authority["authority_id"],
                        "predecessor_event_id": projection.get("head_event_id"),
                        "predecessor_event_sha256": projection.get(
                            "head_event_sha256"
                        ),
                        "candidate_blob_oid": candidate_oid,
                        "candidate_blob_sha256": candidate_sha256,
                        "plan_sha256": candidate["plan_semantic_sha256"],
                    },
                }
            )
            if not apply:
                evidence["terminal_status"] = "validated"
                print("VALIDATED_STATUS_COMPLETION_CANDIDATE")
                return
            gateway_evidence = mutation_gateway.append_status_event(
                reviewed_matches[0],
                stable_id=stable_id,
                from_status=str(expected_update["from_status"]),
                to_status=str(expected_update["to_status"]),
                source_sha=expected_parent,
                head_sha=expected_head,
                candidate_blob_sha256=candidate_sha256,
                plan_sha256=str(candidate["plan_semantic_sha256"]),
                event_name=str(event_name),
                event_ref=str(event_ref),
                run_attempt=str(run_attempt),
                event_before=str(event_before),
                event_after=str(event_after),
                actor=str(actor),
                pusher=str(pusher),
                run_id=str(run_id),
                run_number=str(run_number),
                workflow_ref=str(workflow_ref),
                repository=str(repository),
                event_payload_sha256=str(event_payload_sha256),
                authority_record=authority,
                git_binding=git_binding,
                transport=mutation_transport,
                authority_revalidator=lambda: revalidate_live_authority(
                    root,
                    expected_parent=expected_parent,
                    expected_head=expected_head,
                    main_ref=main_ref,
                    attestation=attestation,
                    run_reader=actions_run_reader,
                    main_fetcher=main_fetcher,
                    caller_proof_verifier=proof_revalidator,  # type: ignore[arg-type]
                ),
            )
        elif authority["authority_type"] == "status_replay":
            candidate_bytes = candidate_path.read_bytes()
            candidate = load_candidate(candidate_bytes)
            validate_git_bindings(
                root,
                candidate,
                candidate_path=candidate_path,
                candidate_bytes=candidate_bytes,
                expected_parent=expected_parent,
                expected_head=expected_head,
                main_ref=main_ref,
            )
            replay = candidate.get("expected_replay")
            if not isinstance(replay, dict):
                raise ValueError("status replay candidate replay contract is malformed")
            if not _is_ancestor(
                root, str(replay.get("reviewed_product_commit", "")), expected_head
            ):
                raise ValueError("status replay reviewed product commit is not in the reviewed head")
            stable_id = str(replay.get("stable_id"))
            source_record = control_state_record(
                load_control_state_at(root, expected_parent),
                stable_id,
                context="source",
            )
            current_record = control_state_record(
                load_control_state_at(root, expected_head), stable_id, context="current"
            )
            validate_candidate(
                candidate,
                plan,
                remote,
                source_record=source_record,
                current_record=current_record,
            )
            candidate_oid = _git(
                root,
                "rev-parse",
                f"{expected_head}:{DEFAULT_CANDIDATE.as_posix()}",
            )
            candidate_sha256 = _canonical_candidate_blob_sha256(root, expected_head)
            if (
                candidate.get("authority_ref") != payload["candidate_authority_ref"]
                or payload["candidate_authority_ref"]
                != mutation_gateway.replay_candidate_authority_ref(payload)
                or payload["candidate_blob_oid"] != candidate_oid
                or payload["candidate_blob_sha256"] != candidate_sha256
                or payload["plan_sha256"] != candidate["plan_semantic_sha256"]
            ):
                raise ValueError("status replay candidate does not bind the committed authority")
            reviewed_matches = [
                issue
                for issue in remote
                if int(issue.get("number", 0)) == payload["issue_number"]
                and str(issue.get("id", "")) == payload["database_id"]
                and str(issue.get("node_id") or issue.get("nodeId") or "")
                == payload["node_id"]
            ]
            if len(reviewed_matches) != 1:
                raise ValueError("status replay authority target issue identity mismatch")
            evidence.update(
                {
                    "remote_inventory_sha256": candidate.get("remote_inventory_sha256"),
                    "plan_semantic_sha256": candidate.get("plan_semantic_sha256"),
                    "authority_ref": candidate.get("authority_ref"),
                    "expected_replay": replay,
                    "candidate_blob_sha256": candidate_sha256,
                    "action_scope": sync.safe_plan_evidence(plan, remote)["actions"],
                    "mutation": {
                        "transport": "github_issue_comment_append",
                        "transport_contract": "one_aggregate_proposal_one_receipt",
                        "authority_id": authority["authority_id"],
                        "replay_hops": replay["transition_history_append"],
                        "reviewed_product_commit": replay["reviewed_product_commit"],
                        "predecessor_event_id": mutation_gateway.project_status_events(
                            reviewed_matches[0]
                        ).get("head_event_id"),
                        "predecessor_event_sha256": mutation_gateway.project_status_events(
                            reviewed_matches[0]
                        ).get("head_event_sha256"),
                        "candidate_blob_oid": candidate_oid,
                        "candidate_blob_sha256": candidate_sha256,
                        "plan_sha256": candidate["plan_semantic_sha256"],
                    },
                }
            )
            if not apply:
                evidence["terminal_status"] = "validated"
                print("VALIDATED_STATUS_REPLAY_CANDIDATE")
                return
            gateway_evidence = mutation_gateway.append_status_replay(
                reviewed_matches[0],
                stable_id=str(payload["stable_id"]),
                issue_number=int(payload["issue_number"]),
                database_id=str(payload["database_id"]),
                node_id=str(payload["node_id"]),
                from_status=str(payload["from_status"]),
                to_status=str(payload["to_status"]),
                reviewed_product_commit=str(payload["reviewed_product_commit"]),
                hops=list(payload["hops"]),
                source_sha=expected_parent,
                head_sha=expected_head,
                candidate_blob_sha256=candidate_sha256,
                plan_sha256=str(candidate["plan_semantic_sha256"]),
                event_name=str(event_name),
                event_ref=str(event_ref),
                run_attempt=str(run_attempt),
                event_before=str(event_before),
                event_after=str(event_after),
                actor=str(actor),
                pusher=str(pusher),
                run_id=str(run_id),
                run_number=str(run_number),
                workflow_ref=str(workflow_ref),
                repository=str(repository),
                event_payload_sha256=str(event_payload_sha256),
                authority_record=authority,
                git_binding=git_binding,
                transport=mutation_transport,
                authority_revalidator=lambda: revalidate_live_authority(
                    root,
                    expected_parent=expected_parent,
                    expected_head=expected_head,
                    main_ref=main_ref,
                    attestation=attestation,
                    run_reader=actions_run_reader,
                    main_fetcher=main_fetcher,
                    caller_proof_verifier=proof_revalidator,  # type: ignore[arg-type]
                ),
            )
        elif authority["authority_type"] == "create":
            actions = plan.get("actions")
            create_body = (
                sync.managed_block(actions[0])
                if isinstance(actions, list)
                and len(actions) == 1
                and actions[0].get("kind") == "create"
                else None
            )
            mutation_gateway.validate_reviewed_create_authority(
                plan,
                approved_sha256=str(payload["plan_sha256"]),
                create_body=create_body,
                authority_record=authority,
                git_binding=git_binding,
                event_name=str(event_name),
                event_ref=str(event_ref),
                run_attempt=str(run_attempt),
                event_before=str(event_before),
                event_after=str(event_after),
                actor=str(actor),
                pusher=str(pusher),
                run_id=str(run_id),
                run_number=str(run_number),
                workflow_ref=str(workflow_ref),
                repository=str(repository),
                event_payload_sha256=str(event_payload_sha256),
            )
            if not apply:
                evidence["action_scope"] = sync.safe_plan_evidence(plan, remote)[
                    "actions"
                ]
                evidence["terminal_status"] = "validated"
                print("VALIDATED_GITHUB_CREATE_AUTHORITY")
                return
            gateway_evidence = sync.apply_actions(
                plan,
                approved_sha256=str(payload["plan_sha256"]),
                mutation_transport=mutation_transport,
                authority_record=authority,
                git_binding=git_binding,
                event_name=str(event_name),
                event_ref=str(event_ref),
                run_attempt=str(run_attempt),
                event_before=str(event_before),
                event_after=str(event_after),
                actor=str(actor),
                pusher=str(pusher),
                run_id=str(run_id),
                run_number=str(run_number),
                workflow_ref=str(workflow_ref),
                repository=str(repository),
                event_payload_sha256=str(event_payload_sha256),
                authority_revalidator=lambda: revalidate_live_authority(
                    root,
                    expected_parent=expected_parent,
                    expected_head=expected_head,
                    main_ref=main_ref,
                    attestation=attestation,
                    run_reader=actions_run_reader,
                    main_fetcher=main_fetcher,
                    caller_proof_verifier=proof_revalidator,  # type: ignore[arg-type]
                ),
            )
        else:
            raise ValueError("unsupported GitHub mutation authority")
        evidence["mutation"] = gateway_evidence
        if not gateway_evidence.get("accepted"):
            raise RuntimeError(
                f"authority projection not accepted: {gateway_evidence['terminal_status']}"
            )
        readback_remote = remote_reader()
        reconciliation = mutation_gateway.reconcile_authority_ledger(
            records, readback_remote, root=root
        )
        readback = sync.plan_actions(
            registry,
            readback_remote,
            historical_map=historical_map,
            authority_records=records,
            authority_root=root,
        )
        if (
            not reconciliation.get("accepted")
            or readback.get("summary") != ZERO_SUMMARY
            or readback.get("actions") != []
        ):
            evidence["zero_action_readback"] = False
            raise RuntimeError("GitHub authority read-back is not fully reconciled")
        evidence["terminal_status"] = "applied_and_verified"
        evidence["zero_action_readback"] = True
        print("APPLIED_AND_VERIFIED_GITHUB_MUTATION_AUTHORITY")
        return
    except Exception as exc:
        if isinstance(exc, mutation_gateway.MutationGatewayError):
            evidence["mutation"] = exc.evidence
        evidence["failure_reason"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if evidence_out is not None:
            evidence_out.parent.mkdir(parents=True, exist_ok=True)
            evidence_out.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )


def main(
    argv: list[str] | None = None,
    *,
    actions_run_reader: Callable[[str], dict[str, Any]] = read_actions_run,
    main_fetcher: Callable[[Path], None] = fetch_origin_main,
    check_run_reader: Callable[[str], dict[str, Any]] = read_check_run,
    oidc_token_requester: Callable[[str], str] = request_actions_oidc_token,
    oidc_jwks_reader: Callable[[], dict[str, Any]] = read_oidc_jwks,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--expected-parent")
    parser.add_argument("--expected-head")
    parser.add_argument("--main-ref")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    candidate = args.candidate
    if not candidate.is_absolute():
        candidate = root / candidate
    evidence_out = args.evidence_out
    if evidence_out is not None and not evidence_out.is_absolute():
        evidence_out = root / evidence_out
    attestation: dict[str, str] = {}
    caller_proof_verifier: Callable[[], None] | None = None
    if args.apply:
        if args.expected_parent or args.expected_head or args.main_ref:
            parser.error(
                "--apply derives push identity and main authority from GitHub Actions"
            )
        attestation = github_actions_push_attestation(actions_run_reader)
        expected_parent = attestation["event_before"]
        expected_head = attestation["event_after"]
        main_ref = "origin/main"
        used_jtis: set[str] = set()
        def caller_proof() -> None:
            verify_fresh_caller_proof(
                attestation,
                run_reader=actions_run_reader,
                check_reader=check_run_reader,
                token_requester=oidc_token_requester,
                jwks_reader=oidc_jwks_reader,
                used_jtis=used_jtis,
            )

        caller_proof_verifier = caller_proof
    else:
        if not args.expected_parent or not args.expected_head:
            parser.error("validation requires --expected-parent and --expected-head")
        expected_parent = args.expected_parent
        expected_head = args.expected_head
        main_ref = args.main_ref
    run(
        root,
        candidate,
        expected_parent=expected_parent,
        expected_head=expected_head,
        main_ref=main_ref,
        apply=args.apply,
        evidence_out=evidence_out,
        event_name=attestation.get("event_name"),
        event_ref=attestation.get("event_ref"),
        run_attempt=attestation.get("run_attempt"),
        event_before=attestation.get("event_before"),
        event_after=attestation.get("event_after"),
        actor=attestation.get("actor"),
        pusher=attestation.get("pusher"),
        run_id=attestation.get("run_id"),
        run_number=attestation.get("run_number"),
        workflow_ref=attestation.get("workflow_ref"),
        repository=attestation.get("repository"),
        event_payload_sha256=attestation.get("event_payload_sha256"),
        actions_run_reader=actions_run_reader,
        main_fetcher=main_fetcher,
        caller_proof_verifier=caller_proof_verifier,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
