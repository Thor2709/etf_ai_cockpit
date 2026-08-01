from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from scripts import apply_reviewed_status_completion as completion
from scripts import github_mutation_gateway as gateway
from scripts import sync_github_issues as sync


PARENT = "a" * 40
HEAD = "b" * 40
MERGE = "c" * 40
RUN_ATTESTATION = {
    "run_id": "12345",
    "run_number": "7",
    "workflow_ref": (
        f"{gateway.REPO}/.github/workflows/"
        "programme-status-completion.yml@refs/heads/main"
    ),
    "repository": gateway.REPO,
    "event_payload_sha256": "d" * 64,
}
NOW = 1_800_000_000
TEST_THUMBPRINT = base64.urlsafe_b64encode(b"a" * 20).rstrip(b"=").decode()
OTHER_THUMBPRINT = base64.urlsafe_b64encode(b"b" * 20).rstrip(b"=").decode()


def _jwt_part(value: object) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(value, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()


def _signed_oidc(
    private_key: rsa.RSAPrivateKey,
    audience: str,
    *,
    header: dict[str, object] | None = None,
    **changes: object,
) -> str:
    claims: dict[str, object] = {
        "iss": completion.OIDC_ISSUER,
        "sub": f"repo:{gateway.REPO}:ref:refs/heads/main",
        "aud": audience,
        "jti": "proof-1",
        "iat": NOW,
        "nbf": NOW,
        "exp": NOW + 300,
        "repository": gateway.REPO,
        "repository_id": "987654",
        "event_name": "push",
        "ref": "refs/heads/main",
        "sha": HEAD,
        "workflow_ref": RUN_ATTESTATION["workflow_ref"],
        "workflow_sha": HEAD,
        "run_id": RUN_ATTESTATION["run_id"],
        "run_number": RUN_ATTESTATION["run_number"],
        "run_attempt": "1",
        "runner_environment": "github-hosted",
        "check_run_id": "555",
    }
    claims.update(changes)
    encoded_header = _jwt_part(header or {
        "typ": "JWT", "alg": "RS256", "x5t": TEST_THUMBPRINT, "kid": "test-key",
    })
    encoded_claims = _jwt_part(claims)
    signing_input = f"{encoded_header}.{encoded_claims}".encode()
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{encoded_header}.{encoded_claims}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _jwk(private_key: rsa.RSAPrivateKey, **changes: object) -> dict[str, object]:
    numbers = private_key.public_key().public_numbers()

    def integer(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    key: dict[str, object] = {
        "kty": "RSA", "use": "sig", "alg": "RS256", "kid": "test-key",
        "x5t": TEST_THUMBPRINT, "n": integer(numbers.n), "e": integer(numbers.e),
    }
    key.update(changes)
    return {"keys": [key]}


def _live_check(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": 555,
        "head_sha": HEAD,
        "status": "in_progress",
        "app": {"slug": "github-actions"},
        "details_url": (
            f"https://github.com/{gateway.REPO}/actions/runs/"
            f"{RUN_ATTESTATION['run_id']}/job/999"
        ),
    }
    value.update(changes)
    return value


def _live_actions_run(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": int(RUN_ATTESTATION["run_id"]),
        "repository": {"full_name": gateway.REPO, "id": 987654},
        "path": completion.WORKFLOW_PATH,
        "name": completion.WORKFLOW_NAME,
        "event": "push",
        "head_branch": "main",
        "head_sha": HEAD,
        "run_number": int(RUN_ATTESTATION["run_number"]),
        "run_attempt": 1,
        "status": "in_progress",
    }
    value.update(changes)
    return value


def _record(status: str = "integrated") -> dict[str, object]:
    return {
        "canonical_id": "ISSUE-0179",
        "title": "Atomic programme generation",
        "classification": "proposed_new",
        "ledger_state": "open",
        "programme_status": status,
        "priority": "P1",
        "owner": "programme-governance",
        "phase": "phase-01-governance-scope",
        "blocking_dependencies": [],
        "required_inputs": [],
        "activation_dependencies": [],
        "capability_lane": "CORE_ANALYSIS",
        "release_blocking": True,
        "downstream_issues": [],
        "related_issues": [],
    }


def _remote(status: str = "implemented_initially") -> list[dict[str, object]]:
    record = _record(status)
    body = sync.managed_block(record)
    return [
        {
            "id": "4179",
            "node_id": "ISSUE_NODE_179",
            "number": 179,
            "title": record["title"],
            "body": body,
            "state": "OPEN",
            "url": "https://example.invalid/issues/179",
        }
    ]


def _bootstrap() -> dict[str, object]:
    return gateway.build_authority_record(
        "legacy_bootstrap",
        {
            "legacy_issues": [
                {
                    "stable_id": "ISSUE-0179",
                    "issue_number": 179,
                    "database_id": "4179",
                    "node_id": "ISSUE_NODE_179",
                    "initial_status": "implemented_initially",
                }
            ]
        },
        sequence=0,
        previous_authority_id=None,
    )


def _plan_and_candidate() -> tuple[
    list[dict[str, object]], dict[str, object], dict[str, object]
]:
    remote = _remote()
    plan = sync.plan_actions(
        {"records": [_record()]},
        remote,
        historical_map={},
        authority_records=[_bootstrap()],
    )
    authority_core = {
        "stable_id": "ISSUE-0179",
        "issue_number": 179,
        "database_id": "4179",
        "node_id": "ISSUE_NODE_179",
        "source_sha": PARENT,
        "from_status": "implemented_initially",
        "to_status": "integrated",
        "plan_sha256": plan["plan_sha256"],
    }
    candidate = {
        "schema_version": completion.SCHEMA_VERSION,
        "execution_allowed": False,
        "expected_parent_sha": PARENT,
        "authority_ref": gateway.candidate_authority_ref(authority_core),
        "remote_inventory_sha256": plan["remote_inventory_sha256"],
        "plan_semantic_sha256": plan["plan_sha256"],
        "expected_update": {
            "stable_id": "ISSUE-0179",
            "from_status": "implemented_initially",
            "to_status": "integrated",
        },
    }
    return remote, plan, candidate


def _status_authority(
    plan: dict[str, object], candidate: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    payload: dict[str, object] = {
        "stable_id": "ISSUE-0179",
        "issue_number": 179,
        "database_id": "4179",
        "node_id": "ISSUE_NODE_179",
        "source_sha": PARENT,
        "from_status": "implemented_initially",
        "to_status": "integrated",
        "candidate_path": gateway.AUTHORITY_CANDIDATE_PATH,
        "candidate_blob_oid": "3" * 40,
        "candidate_blob_sha256": "e" * 64,
        "candidate_authority_ref": candidate["authority_ref"],
        "plan_sha256": plan["plan_sha256"],
    }
    bootstrap = _bootstrap()
    authority = gateway.build_authority_record(
        "status",
        payload,
        sequence=1,
        previous_authority_id=str(bootstrap["authority_id"]),
    )
    binding = {
        "authority_id": authority["authority_id"],
        "authority_sequence": 1,
        "authority_type": "status",
        "source_sha": PARENT,
        "head_sha": HEAD,
        "ledger_blob_oid": "4" * 40,
        "ledger_blob_sha256": "5" * 64,
    }
    return authority, binding


def _create_plan_authority() -> tuple[
    list[dict[str, object]],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    remote = _remote()
    existing = _record("implemented_initially")
    new_record = _record("planned")
    new_record["canonical_id"] = "ISSUE-0180"
    new_record["title"] = "Parallel validation pilot"
    registry_payload = {"records": [existing, new_record]}
    bootstrap = _bootstrap()
    plan = sync.plan_actions(
        registry_payload,
        remote,
        historical_map={},
        authority_records=[bootstrap],
    )
    action = plan["actions"][0]
    authority = gateway.build_authority_record(
        "create",
        {
            "stable_id": action["stable_id"],
            "source_sha": PARENT,
            "title": action["title"],
            "managed_body": sync.managed_block(action),
            "claim_inventory_sha256": plan["claim_inventory_sha256"],
            "plan_sha256": plan["plan_sha256"],
        },
        sequence=1,
        previous_authority_id=str(bootstrap["authority_id"]),
    )
    binding = {
        "authority_id": authority["authority_id"],
        "authority_sequence": 1,
        "authority_type": "create",
        "source_sha": PARENT,
        "head_sha": HEAD,
        "ledger_blob_oid": "1" * 40,
        "ledger_blob_sha256": "2" * 64,
    }
    return remote, registry_payload, plan, authority, binding


def test_happy_apply_uses_approved_plan_and_requires_zero_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, plan, candidate = _plan_and_candidate()
    candidate_path = tmp_path / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    registry = tmp_path / sync.REGISTRY_PATH
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"records": [_record()]}), encoding="utf-8")
    observed: list[dict[str, object]] = []
    monkeypatch.setattr(
        completion,
        "validate_git_bindings",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        completion, "_canonical_candidate_blob_sha256", lambda *_args: "e" * 64
    )
    authority, binding = _status_authority(plan, candidate)
    monkeypatch.setattr(
        completion.mutation_gateway,
        "validate_authority_git_transition",
        lambda *_args, **_kwargs: ([_bootstrap()], [_bootstrap(), authority], binding),
    )
    monkeypatch.setattr(
        completion,
        "_git",
        lambda *_args: "3" * 40,
    )
    original_reconcile = completion.mutation_gateway.reconcile_authority_ledger

    def reconcile(records: list[dict[str, object]], *args: object, **kwargs: object) -> dict[str, object]:
        if len(records) == 2:
            return {"accepted": True, "projections": []}
        return original_reconcile(records, *args, **kwargs)

    monkeypatch.setattr(
        completion.mutation_gateway,
        "reconcile_authority_ledger",
        reconcile,
    )
    monkeypatch.setattr(
        completion.mutation_gateway,
        "append_status_event",
        lambda reviewed_snapshot, **kwargs: (
            observed.append({"snapshot": reviewed_snapshot, **kwargs})
            or {"accepted": True, "terminal_status": "accepted"}
        ),
    )
    readbacks = iter([remote, _remote("integrated")])
    evidence_path = tmp_path / "artifacts/evidence.json"

    completion.run(
        tmp_path,
        candidate_path,
        expected_parent=PARENT,
        expected_head=HEAD,
        main_ref="origin/main",
        apply=True,
        evidence_out=evidence_path,
        remote_reader=lambda: next(readbacks),
        event_name="push",
        event_ref="refs/heads/main",
        run_attempt="1",
        event_before=PARENT,
        event_after=HEAD,
        actor="merger",
        pusher="merger",
        **RUN_ATTESTATION,
        caller_proof_verifier=lambda: None,
    )

    assert len(observed) == 1
    assert observed[0]["plan_sha256"] == plan["plan_sha256"]
    assert observed[0]["snapshot"] == remote[0]
    assert observed[0]["event_name"] == "push"
    assert observed[0]["event_ref"] == "refs/heads/main"
    assert observed[0]["run_attempt"] == "1"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["terminal_status"] == "applied_and_verified"
    assert evidence["zero_action_readback"] is True
    assert "body" not in json.dumps(evidence).lower()


def test_premerge_create_authority_validation_does_not_require_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, registry_payload, plan, authority, binding = _create_plan_authority()
    registry = tmp_path / sync.REGISTRY_PATH
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps(registry_payload), encoding="utf-8")
    bootstrap = _bootstrap()
    monkeypatch.setattr(
        completion.mutation_gateway,
        "validate_authority_git_transition",
        lambda *_args, **_kwargs: (
            [bootstrap],
            [bootstrap, authority],
            binding,
        ),
    )
    evidence = tmp_path / "create-validation.json"

    completion.run(
        tmp_path,
        tmp_path / "candidate-does-not-exist.json",
        expected_parent=PARENT,
        expected_head=HEAD,
        main_ref=None,
        apply=False,
        evidence_out=evidence,
        remote_reader=lambda: remote,
    )

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["terminal_status"] == "validated"
    assert payload["action_scope"][0]["kind"] == "create"

    altered_payload = dict(authority["payload"])
    altered_payload["title"] = "Manual unreviewed title"
    altered = gateway.build_authority_record(
        "create",
        altered_payload,
        sequence=1,
        previous_authority_id=str(bootstrap["authority_id"]),
    )
    altered_binding = {**binding, "authority_id": altered["authority_id"]}
    monkeypatch.setattr(
        completion.mutation_gateway,
        "validate_authority_git_transition",
        lambda *_args, **_kwargs: (
            [bootstrap],
            [bootstrap, altered],
            altered_binding,
        ),
    )

    with pytest.raises(
        gateway.MutationPolicyError,
        match="create_request_authority_mismatch",
    ):
        completion.run(
            tmp_path,
            tmp_path / "candidate-does-not-exist.json",
            expected_parent=PARENT,
            expected_head=HEAD,
            main_ref=None,
            apply=False,
            remote_reader=lambda: remote,
        )


@pytest.mark.parametrize(
    ("area", "field", "value"),
    [
        ("payload", "stable_id", "ISSUE-0181"),
        ("payload", "title", "Manual title"),
        ("payload", "managed_body", "manual body"),
        ("payload", "claim_inventory_sha256", "a" * 64),
        ("payload", "plan_sha256", "b" * 64),
        ("payload", "source_sha", "c" * 40),
        ("binding", "authority_type", "status"),
        ("binding", "source_sha", "d" * 40),
        ("binding", "head_sha", "e" * 40),
        ("binding", "ledger_blob_oid", "not-an-oid"),
        ("binding", "ledger_blob_sha256", "not-a-hash"),
    ],
)
def test_shared_create_validator_rejects_manual_authority_or_binding(
    area: str,
    field: str,
    value: object,
) -> None:
    _remote_rows, _registry, plan, authority, binding = _create_plan_authority()
    candidate_authority = copy.deepcopy(authority)
    candidate_binding = dict(binding)
    if area == "payload":
        payload = dict(candidate_authority["payload"])
        payload[field] = value
        candidate_authority = gateway.build_authority_record(
            "create",
            payload,
            sequence=1,
            previous_authority_id=str(_bootstrap()["authority_id"]),
        )
        candidate_binding["authority_id"] = candidate_authority["authority_id"]
    else:
        candidate_binding[field] = value
    action = plan["actions"][0]

    with pytest.raises(
        gateway.MutationPolicyError,
        match="create_request_authority_mismatch",
    ):
        gateway.validate_reviewed_create_authority(
            plan,
            approved_sha256=str(plan["plan_sha256"]),
            create_body=sync.managed_block(action),
            authority_record=candidate_authority,
            git_binding=candidate_binding,
            event_name="push",
            event_ref="refs/heads/main",
            run_attempt="1",
            event_before=PARENT,
            event_after=HEAD,
            actor="merger",
            pusher="merger",
            **RUN_ATTESTATION,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("remote_inventory_sha256", "0" * 64, "inventory"),
        ("plan_semantic_sha256", "0" * 64, "semantic"),
        ("expected_parent_sha", "0" * 40, "parent"),
    ],
)
def test_candidate_rejects_wrong_bindings(field: str, value: str, message: str) -> None:
    remote, plan, candidate = _plan_and_candidate()
    candidate[field] = value

    if field == "expected_parent_sha":
        with pytest.raises(ValueError, match=message):
            completion.validate_git_bindings(
                Path("."),
                candidate,
                candidate_path=Path("."),
                candidate_bytes=b"",
                expected_parent=PARENT,
                expected_head=HEAD,
                main_ref=None,
            )
    else:
        with pytest.raises(ValueError, match=message):
            completion.validate_candidate(candidate, plan, remote)


def _git_repo(tmp_path: Path) -> tuple[Path, Path, dict[str, object], str, str]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
    marker = root / "marker.txt"
    marker.write_text("parent\n", encoding="utf-8")
    subprocess.run(["git", "add", "marker.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "parent"], cwd=root, check=True)
    parent = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    _remote_rows, _plan, candidate = _plan_and_candidate()
    candidate["expected_parent_sha"] = parent
    candidate_path = root / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(
        json.dumps(candidate, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    attributes = root / ".gitattributes"
    attributes.write_text(
        f"{completion.DEFAULT_CANDIDATE.as_posix()} text\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", ".gitattributes", completion.DEFAULT_CANDIDATE.as_posix()],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=root, check=True)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    return root, candidate_path, candidate, parent, head


def _validate_repo_binding(
    root: Path,
    candidate_path: Path,
    candidate: dict[str, object],
    parent: str,
    head: str,
) -> None:
    completion.validate_git_bindings(
        root,
        candidate,
        candidate_path=candidate_path,
        candidate_bytes=candidate_path.read_bytes() if candidate_path.exists() else b"",
        expected_parent=parent,
        expected_head=head,
        main_ref=None,
    )


def test_candidate_git_binding_accepts_clean_crlf_checkout(tmp_path: Path) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    subprocess.run(["git", "config", "core.autocrlf", "true"], cwd=root, check=True)
    candidate_path.unlink()
    subprocess.run(["git", "reset", "--hard", "-q", "HEAD"], cwd=root, check=True)
    assert b"\r\n" in candidate_path.read_bytes()

    _validate_repo_binding(root, candidate_path, candidate, parent, head)


@pytest.mark.parametrize(
    "change", ["edit", "delete", "staged_edit", "untracked_replacement"]
)
def test_candidate_git_binding_rejects_dirty_or_replaced_path(
    tmp_path: Path, change: str
) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    if change == "edit":
        candidate_path.write_text("{}\n", encoding="utf-8")
    elif change == "delete":
        candidate_path.unlink()
    elif change == "staged_edit":
        candidate_path.write_text("{}\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", completion.DEFAULT_CANDIDATE.as_posix()],
            cwd=root,
            check=True,
        )
    else:
        original = candidate_path.read_bytes()
        subprocess.run(
            ["git", "rm", "--cached", completion.DEFAULT_CANDIDATE.as_posix()],
            cwd=root,
            check=True,
        )
        candidate_path.write_bytes(original)

    with pytest.raises(ValueError, match="not tracked|staged, unstaged, or untracked"):
        _validate_repo_binding(root, candidate_path, candidate, parent, head)


def test_candidate_git_binding_rejects_wrong_head_and_path(tmp_path: Path) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    with pytest.raises(ValueError, match="does not contain"):
        _validate_repo_binding(root, candidate_path, candidate, parent, parent)

    wrong_path = root / "candidate.json"
    wrong_path.write_bytes(candidate_path.read_bytes())
    with pytest.raises(ValueError, match="canonical status-completion path"):
        _validate_repo_binding(root, wrong_path, candidate, parent, head)


@pytest.mark.parametrize(
    "altered",
    [
        b'{"altered": true}\n',
        b'{\r\n  "altered": true\n}\r\n',
        b'{"altered": true}\r',
    ],
)
def test_candidate_git_binding_rejects_altered_bytes_hidden_by_clean_filter(
    tmp_path: Path, altered: bytes
) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    filter_script = root / "clean-filter.py"
    encoded_reviewed = base64.b64encode(candidate_path.read_bytes()).decode("ascii")
    filter_script.write_text(
        "import base64, sys\n"
        f"sys.stdout.buffer.write(base64.b64decode('{encoded_reviewed}'))\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
                "config",
                "filter.hide.clean",
                f'"{Path(sys.executable).as_posix()}" "{filter_script.as_posix()}"',
        ],
        cwd=root,
        check=True,
    )
    info_attributes = root / ".git/info/attributes"
    info_attributes.write_text(
        f"{completion.DEFAULT_CANDIDATE.as_posix()} filter=hide\n",
        encoding="utf-8",
    )
    candidate_path.write_bytes(altered)
    subprocess.run(
        ["git", "add", completion.DEFAULT_CANDIDATE.as_posix()],
        cwd=root,
        check=True,
    )
    assert (
        subprocess.check_output(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--",
                completion.DEFAULT_CANDIDATE.as_posix(),
            ],
            cwd=root,
            text=True,
        )
        == ""
    )

    with pytest.raises(ValueError, match="bytes do not match"):
        _validate_repo_binding(root, candidate_path, candidate, parent, head)


def test_candidate_git_binding_rejects_swap_after_byte_capture(tmp_path: Path) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    captured = candidate_path.read_bytes()
    candidate_path.write_text('{"swapped": true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="staged, unstaged, or untracked"):
        completion.validate_git_bindings(
            root,
            candidate,
            candidate_path=candidate_path,
            candidate_bytes=captured,
            expected_parent=parent,
            expected_head=head,
            main_ref=None,
        )


def test_candidate_rejects_disallowed_direct_status_transition() -> None:
    remote, plan, candidate = _plan_and_candidate()
    candidate["expected_update"]["from_status"] = "planned"  # type: ignore[index]
    remote = _remote("planned")
    plan = sync.plan_actions({"records": [_record()]}, remote, historical_map={})
    candidate["remote_inventory_sha256"] = plan["remote_inventory_sha256"]
    candidate["plan_semantic_sha256"] = plan["plan_sha256"]

    with pytest.raises(ValueError, match="canonical direct transition"):
        completion.validate_candidate(candidate, plan, remote)


def test_failure_evidence_is_privacy_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _plan, candidate = _plan_and_candidate()
    remote[0]["body"] = str(remote[0]["body"]) + "\nPRIVATE REMOTE BODY"
    candidate["remote_inventory_sha256"] = "0" * 64
    candidate_path = tmp_path / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    registry = tmp_path / sync.REGISTRY_PATH
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"records": [_record()]}), encoding="utf-8")
    evidence_path = tmp_path / "artifacts/failure.json"
    monkeypatch.setattr(
        completion, "validate_git_bindings", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        completion.mutation_gateway,
        "validate_authority_git_transition",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("inventory")),
    )

    with pytest.raises(ValueError, match="inventory"):
        completion.run(
            tmp_path,
            candidate_path,
            expected_parent=PARENT,
            expected_head=HEAD,
            main_ref=None,
            apply=False,
            evidence_out=evidence_path,
            remote_reader=lambda: remote,
        )

    evidence_text = evidence_path.read_text(encoding="utf-8")
    assert "PRIVATE REMOTE BODY" not in evidence_text
    assert json.loads(evidence_text)["terminal_status"] == "failed"


def test_candidate_rejects_wrong_id_and_non_status_delta() -> None:
    remote, plan, candidate = _plan_and_candidate()
    wrong_id = copy.deepcopy(candidate)
    wrong_id["expected_update"]["stable_id"] = "ISSUE-0180"  # type: ignore[index]
    with pytest.raises(ValueError, match="stable ID"):
        completion.validate_candidate(wrong_id, plan, remote)

    changed = copy.deepcopy(plan)
    changed["actions"][0]["title"] = "Changed title"
    changed["plan_sha256"] = sync.plan_sha256(changed)
    changed_candidate = copy.deepcopy(candidate)
    changed_candidate["plan_semantic_sha256"] = changed["plan_sha256"]
    with pytest.raises(ValueError, match="non-status delta"):
        completion.validate_candidate(changed_candidate, changed, remote)


@pytest.mark.parametrize("kind", ["create", "close", "reopen", "blocked"])
def test_candidate_rejects_non_update_actions(kind: str) -> None:
    remote, plan, candidate = _plan_and_candidate()
    plan["actions"][0]["kind"] = kind
    plan["summary"] = dict(completion.ZERO_SUMMARY)
    plan["summary"][kind] = 1
    plan["plan_sha256"] = sync.plan_sha256(plan)
    candidate["plan_semantic_sha256"] = plan["plan_sha256"]

    with pytest.raises(ValueError, match="exactly one update"):
        completion.validate_candidate(candidate, plan, remote)


def test_candidate_rejects_multiple_actions() -> None:
    remote, plan, candidate = _plan_and_candidate()
    plan["actions"].append(copy.deepcopy(plan["actions"][0]))
    plan["summary"]["update"] = 2
    plan["plan_sha256"] = sync.plan_sha256(plan)
    candidate["plan_semantic_sha256"] = plan["plan_sha256"]

    with pytest.raises(ValueError, match="exactly one update"):
        completion.validate_candidate(candidate, plan, remote)


def test_workflow_permissions_trigger_and_convergence_deferral() -> None:
    root = Path(__file__).resolve().parents[1]
    status_text = (
        root / ".github/workflows/programme-status-completion.yml"
    ).read_text(encoding="utf-8")
    convergence = (root / ".github/workflows/programme-convergence.yml").read_text(
        encoding="utf-8"
    )
    release = (root / ".github/workflows/release-gate.yml").read_text(encoding="utf-8")
    status_workflow = yaml.safe_load(status_text)

    assert status_workflow["permissions"] == {
        "actions": "read",
        "checks": "read",
        "contents": "read",
        "id-token": "write",
        "issues": "write",
    }
    steps = status_workflow["jobs"]["apply-reviewed-status"]["steps"]
    action_pins = {
        "actions/checkout": ("11bd71901bbe5b1630ceea73d27597364c9af683", "v4.2.2"),
        "actions/setup-python": ("a26af69be951a213d495a4c3e4e4022e16d87065", "v5.6.0"),
        "actions/upload-artifact": ("ea165f8d65b6e75b540449e92b4886f43607fa02", "v4.6.2"),
    }
    for action, (sha, version) in action_pins.items():
        assert f"uses: {action}@{sha} # {version}" in status_text
    executable_actions = [step["uses"] for step in steps if "uses" in step]
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in executable_actions)
    setup_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("uses", "").startswith("actions/setup-python@")
    )
    install_index = next(
        index for index, step in enumerate(steps) if step.get("name") == "Install locked mutation runtime"
    )
    mutation_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Guard and apply reviewed status completion"
    )
    assert steps[setup_index]["with"]["python-version"] == "3.12.10"
    install = steps[install_index]["run"]
    assert "requirements-github-mutation-runtime.txt" in install
    assert "--require-hashes" in install
    assert "--only-binary=:all:" in install
    assert "--no-deps" not in install
    assert '"cryptography": "49.0.0"' in install
    assert '"cffi": "2.0.0"' in install
    assert '"pycparser": "2.23"' in install
    assert "import cffi" in install
    assert "import cryptography" in install
    assert "import pycparser" in install
    assert setup_index < install_index < mutation_index
    assert status_workflow["concurrency"] == {
        "group": "github-mutations-${{ github.repository }}",
        "cancel-in-progress": False,
        "queue": "max",
    }
    assert status_workflow[True]["push"]["branches"] == ["main"]
    assert status_workflow[True]["push"]["paths"] == [
        ".github/issue-transitions/github-mutation-authority.jsonl"
    ]
    assert "--apply" in status_text
    assert "--expected-parent" not in status_text
    assert "--main-ref" not in status_text
    module_invocation = "python -m scripts.apply_reviewed_status_completion"
    direct_script_invocation = "python scripts/apply_reviewed_status_completion.py"
    assert module_invocation in status_text
    assert direct_script_invocation not in status_text
    assert (
        "--evidence-out artifacts/programme-status-completion/evidence.json"
        in status_text
    )
    assert "if: always()" in status_text
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in status_text
    assert "--control-candidate" not in convergence
    assert "deferring to programme-status-completion zero-action readback" in convergence
    assert 'git diff --quiet "${{ github.event.before }}" "${{ github.sha }}"' in convergence
    assert "git rev-parse HEAD^" not in convergence
    assert "group: github-mutations-${{ github.repository }}" in convergence
    assert "cancel-in-progress: false" in convergence
    assert "queue: max" in convergence
    assert "issues: read" in release
    assert isinstance(yaml.safe_load(release), dict)
    assert "steps.github_authority.outputs.changed == 'true'" in release
    assert module_invocation in release
    assert direct_script_invocation not in release
    assert (
        'git diff --quiet "$ETF_COCKPIT_VALIDATION_BASE_SHA" "$ETF_COCKPIT_VALIDATION_HEAD_SHA" -- "$candidate" || candidate_changed=true'
        in release
    )
    assert ' -- "$ledger" || ledger_changed=true' in release
    assert 'echo "changed=$ledger_changed"' in release
    release_workflow = yaml.safe_load(release)
    preflight = release_workflow["jobs"]["preflight"]
    assert preflight["env"] == {
        "ETF_COCKPIT_VALIDATION_BASE_SHA": "${{ needs.classifier.outputs.base_sha }}",
        "ETF_COCKPIT_VALIDATION_HEAD_SHA": "${{ needs.classifier.outputs.head_sha }}",
    }
    preflight_steps = preflight["steps"]
    primary_checkout = next(
        step for step in preflight_steps if step.get("name") == "Check out source"
    )
    assert primary_checkout["uses"] == "actions/checkout@v4"
    assert primary_checkout["with"] == {"fetch-depth": 0}
    authority_checkout = next(
        step
        for step in preflight_steps
        if step.get("name") == "Check out reviewed GitHub mutation authority head"
    )
    assert "if" not in authority_checkout
    assert authority_checkout["uses"] == (
        "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
    )
    assert authority_checkout["with"] == {
        "repository": "${{ needs.classifier.outputs.head_repository }}",
        "ref": "${{ needs.classifier.outputs.head_sha }}",
        "path": ".validation-head",
        "fetch-depth": 0,
        "persist-credentials": False,
    }
    base_checkout = next(
        step
        for step in preflight_steps
        if step.get("name") == "Check out trusted pull request base"
    )
    assert base_checkout["uses"] == authority_checkout["uses"]
    assert base_checkout["with"] == {
        "repository": "${{ needs.classifier.outputs.base_repository }}",
        "ref": "${{ needs.classifier.outputs.base_sha }}",
        "path": ".validation-base",
        "fetch-depth": 1,
        "persist-credentials": False,
    }
    authority_detection = next(
        step
        for step in preflight_steps
        if step.get("name") == "Detect and couple GitHub mutation authority changes"
    )
    assert authority_detection["working-directory"] == ".validation-head"
    assert (
        'git fetch --no-tags --depth=1 ../.validation-base '
        '"$ETF_COCKPIT_VALIDATION_BASE_SHA"'
        in authority_detection["run"]
    )
    authority_validation = next(
        step
        for step in preflight_steps
        if step.get("name") == "Validate reviewed GitHub mutation authority"
    )
    assert authority_validation["working-directory"] == ".validation-head"
    assert 'checked_head="$(git rev-parse HEAD)"' in authority_validation["run"]
    assert (
        '[[ "$checked_head" != "$ETF_COCKPIT_VALIDATION_HEAD_SHA" ]]'
        in authority_validation["run"]
    )
    assert "--root ." in authority_validation["run"]
    assert '--evidence-out "$STATUS_COMPLETION_EVIDENCE"' in release
    security_end = next(
        index
        for index, step in enumerate(preflight_steps)
        if step.get("name") == "Check out source"
    )
    security_steps = preflight_steps[:security_end]
    security_text = yaml.safe_dump(security_steps)
    assert "needs.classifier.outputs.base_sha" in security_text
    assert "needs.classifier.outputs.head_sha" in security_text
    assert "github.event.pull_request.base.sha" not in security_text
    assert "github.event.pull_request.head.sha" not in security_text
    assert security_steps[0]["name"] == "Validate trusted pull request identities"
    assert [step["name"] for step in security_steps].index(
        "Detect and couple GitHub mutation authority changes"
    ) < [step["name"] for step in security_steps].index(
        "Install locked mutation runtime"
    )
    install = next(
        step for step in security_steps if step.get("name") == "Install locked mutation runtime"
    )["run"]
    assert "requirements-github-mutation-runtime.txt" in install
    assert "--require-hashes" in install
    assert "--only-binary=:all:" in install
    prepare = next(
        step
        for step in security_steps
        if step.get("name") == "Prepare fresh status-completion evidence target"
    )["run"]
    assert 'mktemp -d "$RUNNER_TEMP/status-completion.XXXXXX"' in prepare
    assert '[[ -L "$evidence_dir" ]]' in prepare
    assert "was not initially empty" in prepare
    verify = next(
        step
        for step in security_steps
        if step.get("name") == "Verify fresh status-completion evidence"
    )
    assert "[[ -L \"$STATUS_COMPLETION_EVIDENCE\" ]]" in verify["run"]
    assert "stat -c '%h'" in verify["run"]
    assert "stat -c '%u'" in verify["run"]
    assert "python -I -S" in verify["run"]
    assert 'echo "ready=true"' in verify["run"]
    upload = next(
        step
        for step in security_steps
        if step.get("name") == "Upload status-completion candidate evidence"
    )
    assert upload["if"] == "steps.status_evidence_verified.outputs.ready == 'true'"
    assert upload["with"]["path"] == "${{ steps.status_evidence.outputs.file }}"
    assert "always()" not in upload["if"]
    assert "name: validation-status-completion-candidate-${{ github.sha }}" in release
    write_workflows = []
    for workflow_path in (root / ".github/workflows").glob("*.yml"):
        workflow_text = workflow_path.read_text(encoding="utf-8")
        if "issues: write" in workflow_text:
            write_workflows.append(workflow_path.name)
            assert "group: github-mutations-${{ github.repository }}" in workflow_text
            assert "cancel-in-progress: false" in workflow_text
            assert "queue: max" in workflow_text
    assert write_workflows == ["programme-status-completion.yml"]
    for argument in (
        "--event-name",
        "--event-ref",
        "--run-attempt",
        "--event-before",
        "--event-after",
        "--actor",
        "--pusher",
    ):
        assert argument not in status_text
    candidate_upload = release.index(
        "- name: Upload status-completion candidate evidence"
    )
    assert (
        "if-no-files-found: error" in release[candidate_upload : candidate_upload + 420]
    )


def test_github_mutation_runtime_is_complete_binary_hash_lock() -> None:
    root = Path(__file__).resolve().parents[1]
    lock = (root / "requirements-github-mutation-runtime.txt").read_text(
        encoding="utf-8"
    )
    requirements = re.findall(
        r"(?m)^([a-z0-9-]+)==([^ ]+) \\\n+\s+--hash=sha256:([0-9a-f]{64})$",
        lock,
    )
    assert requirements == [
        (
            "cffi",
            "2.0.0",
            "3e17ed538242334bf70832644a32a7aae3d83b57567f9fd60a26257e992b79ba",
        ),
        (
            "cryptography",
            "49.0.0",
            "0e959b578856a3924bc0cbb710fc12c387b9412a951389f3ca61704a9e25f325",
        ),
        (
            "pycparser",
            "2.23",
            "e5c6e8d3fbad53479cab09ac03729e0a9faf2bee3db8208a550daf5af81a5934",
        ),
    ]
    requirement_lines = [
        line for line in lock.splitlines() if line and not line.startswith(("#", " "))
    ]
    assert len(requirement_lines) == 3
    assert all(
        re.fullmatch(r"[a-z0-9-]+==[0-9.]+ [\\]", line)
        for line in requirement_lines
    )


def test_authority_transition_accepts_multi_commit_push_and_not_head_parent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "authority-repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    ledger = root / gateway.AUTHORITY_PATH
    ledger.parent.mkdir(parents=True)
    bootstrap = _bootstrap()
    ledger.write_bytes(gateway.authority_ledger_bytes([bootstrap]))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "bootstrap"], cwd=root, check=True)
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()

    candidate = root / completion.DEFAULT_CANDIDATE
    candidate.write_text("{}\n", encoding="utf-8", newline="\n")
    candidate_oid = subprocess.check_output(
        ["git", "hash-object", completion.DEFAULT_CANDIDATE.as_posix()],
        cwd=root,
        text=True,
    ).strip()
    payload: dict[str, object] = {
        "stable_id": "ISSUE-0179",
        "issue_number": 179,
        "database_id": "4179",
        "node_id": "ISSUE_NODE_179",
        "source_sha": source,
        "from_status": "implemented_initially",
        "to_status": "integrated",
        "candidate_path": gateway.AUTHORITY_CANDIDATE_PATH,
        "candidate_blob_oid": candidate_oid,
        "candidate_blob_sha256": __import__("hashlib").sha256(b"{}\n").hexdigest(),
        "candidate_authority_ref": "",
        "plan_sha256": "2" * 64,
    }
    payload["candidate_authority_ref"] = gateway.candidate_authority_ref(payload)
    authority = gateway.build_authority_record(
        "status",
        payload,
        sequence=1,
        previous_authority_id=str(bootstrap["authority_id"]),
    )
    ledger.write_bytes(gateway.authority_ledger_bytes([bootstrap, authority]))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "authority"], cwd=root, check=True)
    (root / "ordinary.txt").write_text("later\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "ordinary"], cwd=root, check=True)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()

    before, after, binding = gateway.validate_authority_git_transition(
        root,
        event_before=source,
        event_after=head,
        main_ref=None,
    )
    assert before == [bootstrap]
    assert after == [bootstrap, authority]
    assert binding["head_sha"] == head


def test_live_revalidator_fetches_remote_main_and_detects_advance(
    tmp_path: Path,
) -> None:
    bare = tmp_path / "origin.git"
    root = tmp_path / "writer"
    advancer = tmp_path / "advancer"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "checkout", "-qb", "main"], cwd=root, check=True)
    for key, value in (
        ("user.name", "Test"),
        ("user.email", "test@example.invalid"),
    ):
        subprocess.run(["git", "config", key, value], cwd=root, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)], cwd=root, check=True
    )
    ledger = root / gateway.AUTHORITY_PATH
    ledger.parent.mkdir(parents=True)
    bootstrap = _bootstrap()
    ledger.write_bytes(gateway.authority_ledger_bytes([bootstrap]))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "bootstrap"], cwd=root, check=True)
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    subprocess.run(
        ["git", "push", "-qu", "origin", "main"], cwd=root, check=True
    )

    candidate = root / completion.DEFAULT_CANDIDATE
    candidate.write_bytes(b"{}\n")
    candidate_oid = subprocess.check_output(
        ["git", "hash-object", completion.DEFAULT_CANDIDATE.as_posix()],
        cwd=root,
        text=True,
    ).strip()
    status_payload: dict[str, object] = {
        "stable_id": "ISSUE-0179",
        "issue_number": 179,
        "database_id": "4179",
        "node_id": "ISSUE_NODE_179",
        "source_sha": source,
        "from_status": "implemented_initially",
        "to_status": "integrated",
        "candidate_path": gateway.AUTHORITY_CANDIDATE_PATH,
        "candidate_blob_oid": candidate_oid,
        "candidate_blob_sha256": __import__("hashlib").sha256(b"{}\n").hexdigest(),
        "candidate_authority_ref": "",
        "plan_sha256": "2" * 64,
    }
    status_payload["candidate_authority_ref"] = gateway.candidate_authority_ref(
        status_payload
    )
    authority = gateway.build_authority_record(
        "status",
        status_payload,
        sequence=1,
        previous_authority_id=str(bootstrap["authority_id"]),
    )
    ledger.write_bytes(gateway.authority_ledger_bytes([bootstrap, authority]))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "authority"], cwd=root, check=True)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=root, check=True)
    attestation = {**RUN_ATTESTATION, "event_after": head}

    def run_reader(_run_id: str) -> dict[str, object]:
        return _live_actions_run(head_sha=head)

    completion.revalidate_live_authority(
        root,
        expected_parent=source,
        expected_head=head,
        main_ref="origin/main",
        attestation=attestation,
        run_reader=run_reader,
        main_fetcher=completion.fetch_origin_main,
        caller_proof_verifier=lambda: None,
    )

    subprocess.run(
        ["git", "clone", "-q", "--branch", "main", str(bare), str(advancer)],
        check=True,
    )
    for key, value in (
        ("user.name", "Advancer"),
        ("user.email", "advancer@example.invalid"),
    ):
        subprocess.run(["git", "config", key, value], cwd=advancer, check=True)
    (advancer / "advance.txt").write_text("new main\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=advancer, check=True)
    subprocess.run(["git", "commit", "-qm", "advance main"], cwd=advancer, check=True)
    subprocess.run(
        ["git", "push", "-q", "origin", "main"], cwd=advancer, check=True
    )

    with pytest.raises(gateway.MutationPolicyError, match="superseded_on_main"):
        completion.revalidate_live_authority(
            root,
            expected_parent=source,
            expected_head=head,
            main_ref="origin/main",
            attestation=attestation,
            run_reader=run_reader,
            main_fetcher=completion.fetch_origin_main,
            caller_proof_verifier=lambda: None,
        )


def test_status_completion_module_help_smoke() -> None:
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-m", "scripts.apply_reviewed_status_completion", "--help"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "usage:" in result.stdout


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "completed"},
        {"id": 99999},
        {"path": ".github/workflows/other.yml"},
        {"name": "Other workflow"},
        {"head_sha": "f" * 40},
        {"repository": {"full_name": "other/repository"}},
        {"event": "workflow_dispatch"},
        {"head_branch": "feature"},
        {"run_number": 8},
        {"run_attempt": 2},
    ],
)
def test_live_actions_attestation_rejects_nonintroducing_or_spent_runs(
    changes: dict[str, object],
) -> None:
    attestation = {**RUN_ATTESTATION, "event_after": HEAD}

    with pytest.raises(
        gateway.MutationPolicyError,
        match="github_actions_run_attestation_mismatch",
    ):
        completion.validate_live_actions_run(
            attestation,
            lambda _run_id: _live_actions_run(**changes),
        )


def test_live_actions_attestation_accepts_only_current_exact_run() -> None:
    attestation = {**RUN_ATTESTATION, "event_after": HEAD}

    completion.validate_live_actions_run(
        attestation,
        lambda run_id: _live_actions_run(id=int(run_id)),
    )


def test_fresh_oidc_proof_binds_exact_issue_credential_and_live_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("GH_TOKEN", "github-token\nwith-exact-bytes")
    audience = hashlib.sha256(os.environ["GH_TOKEN"].encode()).hexdigest()
    token = _signed_oidc(private_key, audience)
    attestation = {**RUN_ATTESTATION, "event_after": HEAD}

    completion.verify_fresh_caller_proof(
        attestation,
        run_reader=lambda _run_id: _live_actions_run(),
        check_reader=lambda _check_id: _live_check(),
        token_requester=lambda requested: token if requested == audience else "",
        jwks_reader=lambda: _jwk(private_key),
        used_jtis=set(),
        now=lambda: NOW,
    )


@pytest.mark.parametrize(
    "header",
    [
        {"typ": "JWT", "alg": "RS256", "x5t": "", "kid": "test-key"},
        {"typ": "JWT", "alg": "RS256", "x5t": 7, "kid": "test-key"},
        {"typ": "JWT", "alg": "RS256", "x5t": OTHER_THUMBPRINT, "kid": "test-key"},
        {"typ": "JWT", "alg": "RS256", "kid": ""},
        {"typ": "JWT", "alg": "RS256", "kid": 7},
        {"typ": "JOSE", "alg": "RS256", "x5t": TEST_THUMBPRINT, "kid": "test-key"},
        {"typ": "JWT", "alg": "ES256", "x5t": TEST_THUMBPRINT, "kid": "test-key"},
        {"typ": "JWT", "alg": "RS256", "x5t": TEST_THUMBPRINT, "kid": "test-key", "jku": "x"},
        {"typ": "JWT", "alg": "RS256", "x5t": TEST_THUMBPRINT, "kid": "test-key", "x5u": "x"},
        {"typ": "JWT", "alg": "RS256", "x5t": TEST_THUMBPRINT, "kid": "test-key", "crit": []},
        {"typ": "JWT", "alg": "RS256", "x5t": TEST_THUMBPRINT, "kid": "test-key", "other": True},
    ],
)
def test_oidc_proof_rejects_noncanonical_or_unbound_jose_header(
    header: dict[str, object],
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    audience = hashlib.sha256(b"real-token").hexdigest()
    with pytest.raises(ValueError):
        completion.verify_actions_oidc_token(
            _signed_oidc(private_key, audience, header=header),
            audience=audience,
            attestation={**RUN_ATTESTATION, "event_after": HEAD},
            live_run=_live_actions_run(),
            live_check=_live_check(),
            jwks_reader=lambda: _jwk(private_key),
            now=lambda: NOW,
        )


@pytest.mark.parametrize(
    ("header", "jwk_x5t"),
    [
        ({"typ": "JWT", "alg": "RS256", "kid": "test-key"}, None),
        (
            {
                "typ": "JWT", "alg": "RS256", "kid": "test-key",
                "x5t": TEST_THUMBPRINT,
            },
            TEST_THUMBPRINT,
        ),
        (
            {
                "typ": "JWT", "alg": "RS256", "kid": "test-key",
                "x5t": TEST_THUMBPRINT,
            },
            None,
        ),
        ({"typ": "JWT", "alg": "RS256", "kid": "test-key"}, TEST_THUMBPRINT),
    ],
)
def test_oidc_proof_accepts_optional_thumbprint_shapes(
    header: dict[str, object],
    jwk_x5t: object,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    audience = hashlib.sha256(b"real-token").hexdigest()
    jwks = _jwk(private_key, x5t=jwk_x5t)
    if jwk_x5t is None:
        del jwks["keys"][0]["x5t"]  # type: ignore[index]

    completion.verify_actions_oidc_token(
        _signed_oidc(private_key, audience, header=header),
        audience=audience,
        attestation={**RUN_ATTESTATION, "event_after": HEAD},
        live_run=_live_actions_run(),
        live_check=_live_check(),
        jwks_reader=lambda: jwks,
        now=lambda: NOW,
    )


@pytest.mark.parametrize(
    "x5t",
    [
        "",
        7,
        OTHER_THUMBPRINT,
        "*" * 27,
        f"{TEST_THUMBPRINT}=",
        base64.urlsafe_b64encode(b"a" * 19).rstrip(b"=").decode(),
    ],
)
def test_oidc_proof_rejects_malformed_or_mismatched_jwk_thumbprint(
    x5t: object,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    audience = hashlib.sha256(b"real-token").hexdigest()
    jwks = _jwk(private_key, x5t=x5t)
    with pytest.raises(ValueError):
        completion.verify_actions_oidc_token(
            _signed_oidc(private_key, audience),
            audience=audience,
            attestation={**RUN_ATTESTATION, "event_after": HEAD},
            live_run=_live_actions_run(),
            live_check=_live_check(),
            jwks_reader=lambda: jwks,
            now=lambda: NOW,
        )


@pytest.mark.parametrize(
    "x5t",
    [
        "*" * 27,
        f"{TEST_THUMBPRINT}=",
        base64.urlsafe_b64encode(b"a" * 19).rstrip(b"=").decode(),
    ],
)
def test_oidc_proof_rejects_matched_malformed_thumbprints(x5t: str) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    audience = hashlib.sha256(b"real-token").hexdigest()
    header = {"typ": "JWT", "alg": "RS256", "kid": "test-key", "x5t": x5t}

    with pytest.raises(ValueError):
        completion.verify_actions_oidc_token(
            _signed_oidc(private_key, audience, header=header),
            audience=audience,
            attestation={**RUN_ATTESTATION, "event_after": HEAD},
            live_run=_live_actions_run(),
            live_check=_live_check(),
            jwks_reader=lambda: _jwk(private_key, x5t=x5t),
            now=lambda: NOW,
        )


def test_oidc_proof_rejects_duplicate_kid_and_altered_signature() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    audience = hashlib.sha256(b"real-token").hexdigest()
    token = _signed_oidc(private_key, audience)
    jwks = _jwk(private_key)
    jwks["keys"].append(copy.deepcopy(jwks["keys"][0]))  # type: ignore[union-attr]
    arguments = {
        "audience": audience,
        "attestation": {**RUN_ATTESTATION, "event_after": HEAD},
        "live_run": _live_actions_run(),
        "live_check": _live_check(),
        "now": lambda: NOW,
    }

    with pytest.raises(ValueError, match="duplicate GitHub Actions signing key"):
        completion.verify_actions_oidc_token(
            token, jwks_reader=lambda: jwks, **arguments,
        )

    token_parts = token.split(".")
    signature = bytearray(completion._b64url_decode(token_parts[2], "JWT signature"))
    signature[0] ^= 1
    token_parts[2] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    altered_token = ".".join(token_parts)
    with pytest.raises(ValueError, match="invalid GitHub Actions OIDC signature"):
        completion.verify_actions_oidc_token(
            altered_token, jwks_reader=lambda: _jwk(private_key), **arguments,
        )


@pytest.mark.parametrize(
    ("claim_changes", "check_changes"),
    [
        ({"runner_environment": "self-hosted"}, {}),
        ({"workflow_sha": "f" * 40}, {}),
        ({"repository_id": "123"}, {}),
        ({"check_run_id": "556"}, {}),
        ({"iat": NOW - completion.OIDC_MAX_AGE_SECONDS - 1}, {}),
        ({}, {"status": "completed"}),
        ({}, {"head_sha": "f" * 40}),
    ],
)
def test_oidc_proof_rejects_wrong_claims_and_spent_job(
    monkeypatch: pytest.MonkeyPatch,
    claim_changes: dict[str, object],
    check_changes: dict[str, object],
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signed_audience = hashlib.sha256(b"real-token").hexdigest()
    token = _signed_oidc(private_key, signed_audience, **claim_changes)
    monkeypatch.setenv("GH_TOKEN", "real-token")
    attestation = {**RUN_ATTESTATION, "event_after": HEAD}

    with pytest.raises(
        gateway.MutationPolicyError,
        match=(
            "github_check_run_attestation_mismatch"
            if check_changes or claim_changes.get("check_run_id") == "556"
            else "github_actions_oidc_caller_proof_invalid"
        ),
    ):
        completion.verify_fresh_caller_proof(
            attestation,
            run_reader=lambda _run_id: _live_actions_run(),
            check_reader=lambda _check_id: _live_check(**check_changes),
            token_requester=lambda _audience: token,
            jwks_reader=lambda: _jwk(private_key),
            used_jtis=set(),
            now=lambda: NOW,
        )


def test_preissued_proof_cannot_be_reused_with_replacement_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _signed_oidc(private_key, hashlib.sha256(b"original-token").hexdigest())
    monkeypatch.setenv("GH_TOKEN", "replacement-token")
    with pytest.raises(gateway.MutationPolicyError, match="caller_proof_invalid"):
        completion.verify_fresh_caller_proof(
            {**RUN_ATTESTATION, "event_after": HEAD},
            run_reader=lambda _run_id: _live_actions_run(),
            check_reader=lambda _check_id: _live_check(),
            token_requester=lambda _audience: token,
            jwks_reader=lambda: _jwk(private_key),
            used_jtis=set(),
            now=lambda: NOW,
        )


def test_live_oidc_request_authority_can_adapt_to_replacement_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("GH_TOKEN", "replacement-token")
    requested: list[str] = []

    def adaptive_request(audience: str) -> str:
        requested.append(audience)
        return _signed_oidc(private_key, audience)

    completion.verify_fresh_caller_proof(
        {**RUN_ATTESTATION, "event_after": HEAD},
        run_reader=lambda _run_id: _live_actions_run(),
        check_reader=lambda _check_id: _live_check(),
        token_requester=adaptive_request,
        jwks_reader=lambda: _jwk(private_key),
        used_jtis=set(),
        now=lambda: NOW,
    )
    assert requested == [hashlib.sha256(b"replacement-token").hexdigest()]


def test_oidc_proof_jti_cannot_be_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("GH_TOKEN", "real-token")
    audience = hashlib.sha256(b"real-token").hexdigest()
    token = _signed_oidc(private_key, audience)
    used: set[str] = set()
    kwargs = {
        "run_reader": lambda _run_id: _live_actions_run(),
        "check_reader": lambda _check_id: _live_check(),
        "token_requester": lambda _audience: token,
        "jwks_reader": lambda: _jwk(private_key),
        "used_jtis": used,
        "now": lambda: NOW,
    }
    attestation = {**RUN_ATTESTATION, "event_after": HEAD}
    completion.verify_fresh_caller_proof(attestation, **kwargs)
    with pytest.raises(gateway.MutationPolicyError, match="caller_proof_invalid"):
        completion.verify_fresh_caller_proof(attestation, **kwargs)


def test_actions_run_reader_uses_one_read_only_repository_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[list[str]] = []

    def read(args: list[str], **_kwargs: object) -> str:
        observed.append(args)
        return json.dumps(_live_actions_run())

    monkeypatch.setattr(completion.mutation_gateway, "_read_gh", read)

    assert completion.read_actions_run(RUN_ATTESTATION["run_id"])["status"] == (
        "in_progress"
    )
    assert observed == [
        [
            "api",
            f"repos/{gateway.REPO}/actions/runs/{RUN_ATTESTATION['run_id']}",
        ]
    ]


def test_apply_cli_rejects_local_invocation_and_native_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in tuple(os.environ):
        if key.startswith("GITHUB_"):
            monkeypatch.delenv(key, raising=False)
    with pytest.raises(gateway.MutationPolicyError, match="github_actions_apply_required"):
        completion.main(["--root", str(tmp_path), "--apply"])

    event = {
        "before": PARENT,
        "after": HEAD,
        "ref": "refs/heads/main",
        "repository": {"full_name": gateway.REPO},
        "pusher": {"name": "merger"},
        "head_commit": {"id": HEAD},
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    values = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": HEAD,
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_NUMBER": "7",
        "GITHUB_WORKFLOW_REF": RUN_ATTESTATION["workflow_ref"],
        "GITHUB_REPOSITORY": gateway.REPO,
        "GITHUB_ACTOR": "merger",
        "GITHUB_EVENT_PATH": str(event_path),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(gateway.MutationPolicyError, match="ineligible_authority"):
        completion.main(["--root", str(tmp_path), "--apply"])

    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    with pytest.raises(
        gateway.MutationPolicyError,
        match="github_actions_run_attestation_mismatch",
    ):
        completion.main(
            ["--root", str(tmp_path), "--apply"],
            actions_run_reader=lambda _run_id: _live_actions_run(
                id=99999,
                status="completed",
            ),
            main_fetcher=lambda _root: None,
        )


def test_outside_job_forged_context_pat_and_borrowed_live_run_never_posts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = {
        "before": PARENT,
        "after": HEAD,
        "ref": "refs/heads/main",
        "repository": {"full_name": gateway.REPO},
        "pusher": {"name": "merger"},
        "head_commit": {"id": HEAD},
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    values = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": HEAD,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": RUN_ATTESTATION["run_id"],
        "GITHUB_RUN_NUMBER": RUN_ATTESTATION["run_number"],
        "GITHUB_WORKFLOW_REF": RUN_ATTESTATION["workflow_ref"],
        "GITHUB_REPOSITORY": gateway.REPO,
        "GITHUB_ACTOR": "merger",
        "GITHUB_EVENT_PATH": str(event_path),
        "GH_TOKEN": "forged-local-pat",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ACTIONS_ID_TOKEN_REQUEST_URL", raising=False)
    monkeypatch.delenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", raising=False)
    posts = 0

    def forbidden_transport() -> object:
        nonlocal posts
        posts += 1
        raise AssertionError("mutation transport reached")

    monkeypatch.setattr(gateway, "GhMutationTransport", forbidden_transport)
    with pytest.raises(gateway.MutationPolicyError, match="caller_proof_invalid"):
        completion.main(
            ["--root", str(tmp_path), "--apply"],
            actions_run_reader=lambda _run_id: _live_actions_run(),
            main_fetcher=lambda _root: None,
        )
    assert posts == 0
