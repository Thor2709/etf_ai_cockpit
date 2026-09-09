"""Offline capability tests: all remote writes terminate in an in-memory transport."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import apply_reviewed_status_completion as completion
from scripts import github_mutation_gateway as gateway
from scripts import prepare_github_mutation_authority as preparation
from scripts import sync_github_issues as sync


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


class Memory:
    def __init__(self, remote: list[dict[str, Any]], failure: str = "", fail_number: int = 2):
        self.remote = copy.deepcopy(remote)
        self.failure = failure
        self.fail_number = fail_number
        self.writes: list[int] = []

    def list_issues(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.remote)

    def fetch_issue(self, number: int) -> dict[str, Any]:
        return copy.deepcopy(next(row for row in self.remote if row["number"] == number))

    def _refresh_managed_body(self, number: int, body: str) -> None:
        self.writes.append(number)
        row = next(row for row in self.remote if row["number"] == number)
        if number == self.fail_number and self.failure == "pre":
            raise TimeoutError("response lost")
        row["body"] = body
        if number == self.fail_number:
            if self.failure == "third":
                row["body"] += " concurrent human note"
            elif self.failure == "labels":
                row["labels"] = ["changed"]
            elif self.failure == "comment":
                row["comments"].append({"id": "new", "body": "new comment"})
            elif self.failure == "assignees":
                row["assignees"] = [{"id": 90, "node_id": "NEW_USER", "login": "new"}]
            elif self.failure == "milestone":
                row["milestone"] = {"id": 99, "node_id": "NEW_MILESTONE", "number": 99}
            if self.failure:
                raise TimeoutError("response lost")


@pytest.fixture
def prepared(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    records = []
    remote = []
    identities = []
    for number in (1, 2, 3):
        stable_id = f"ISSUE-{number:04d}"
        record = {
            "canonical_id": stable_id, "title": f"Issue {number}",
            "classification": "proposed_new", "ledger_state": "open",
            "programme_status": "planned", "priority": "P1", "owner": "owner",
            "phase": "phase-01", "blocking_dependencies": [], "required_inputs": [],
            "activation_dependencies": [], "capability_lane": "CORE_ANALYSIS",
            "release_blocking": True, "downstream_issues": [], "related_issues": [],
        }
        old = {**record, "blocking_dependencies": ["ISSUE-0999"]}
        records.append(record)
        remote.append({
            "number": number, "id": str(100 + number), "node_id": f"NODE_{number}",
            "title": record["title"], "state": "open", "labels": ["human"],
            "body": "human prefix\r\n\n" + sync.managed_block(old) + "\n\r\n human suffix ",
            "url": f"https://example.invalid/issues/{number}", "comments": [],
            "assignees": [{"id": 10, "node_id": "USER_10", "login": "owner"}],
            "milestone": {"id": 20, "node_id": "MILESTONE_20", "number": 1,
                          "title": "Release", "state": "open"},
        })
        identities.append({
            "stable_id": stable_id, "issue_number": number,
            "database_id": str(100 + number), "node_id": f"NODE_{number}",
            "initial_status": "planned",
        })
    registry = {"records": records, "execution_allowed": False}
    registry_path = root / gateway.REFRESH_REGISTRY_PATH
    registry_path.parent.mkdir()
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    bootstrap = gateway.build_authority_record(
        "legacy_bootstrap", {"legacy_issues": identities}, sequence=0, previous_authority_id=None,
    )
    ledger_path = root / gateway.AUTHORITY_PATH
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_bytes(gateway.authority_ledger_bytes([bootstrap]))
    git(root, "add", ".")
    git(root, "commit", "-qm", "source")
    source = git(root, "rev-parse", "HEAD")
    plan = sync.plan_actions(registry, remote, authority_records=[bootstrap], authority_root=root)
    candidate, ledger, manifest = preparation.prepare(
        root, plan, remote, source_sha=source, mode="managed_refresh",
    )
    assert candidate is None
    ledger_path.write_bytes(ledger)
    git(root, "add", ".")
    git(root, "commit", "-qm", "authority")
    head = git(root, "rev-parse", "HEAD")
    _, authorities, binding = gateway.validate_authority_git_transition(
        root, event_before=source, event_after=head, main_ref=None,
    )
    attestation = {
        "run_id": "1", "run_number": "1", "repository": gateway.REPO,
        "workflow_ref": f"{gateway.REPO}/.github/workflows/programme-status-completion.yml@refs/heads/main",
        "event_payload_sha256": "e" * 64, "event_name": "push",
        "event_ref": "refs/heads/main", "run_attempt": "1",
        "event_before": source, "event_after": head, "actor": "owner", "pusher": "owner",
    }
    return dict(root=root, registry=registry, remote=remote, plan=plan, source=source,
                head=head, authority=authorities[-1], binding=binding,
                attestation=attestation, bootstrap=bootstrap, manifest=manifest)


def apply(data: dict[str, Any], memory: Memory) -> dict[str, Any]:
    return gateway.apply_reviewed_managed_refresh(
        data["root"], data["plan"], data["remote"], authority_record=data["authority"],
        git_binding=data["binding"], attestation=data["attestation"],
        authority_revalidator=lambda: None, transport=memory,
    )


def resign(plan: dict[str, Any]) -> None:
    plan["plan_sha256"] = sync.plan_sha256(plan)


def test_exact_batch_and_outside_bytes(prepared: dict[str, Any]) -> None:
    memory = Memory(prepared["remote"])
    assert apply(prepared, memory)["accepted"]
    assert memory.writes == [1, 2, 3]
    for old, new in zip(prepared["remote"], memory.remote, strict=True):
        assert new["body"].startswith("human prefix\r\n\n")
        assert new["body"].endswith("\n\r\n human suffix ")
        assert {k: v for k, v in new.items() if k != "body"} == {k: v for k, v in old.items() if k != "body"}
    assert gateway.reconcile_authority_ledger(
        [prepared["bootstrap"], prepared["authority"]], memory.remote,
    )["accepted"]
    readback = sync.plan_actions(prepared["registry"], memory.remote)
    assert readback["actions"] == []


@pytest.mark.parametrize("field,value", [
    ("issue_number", 99), ("stable_id", "ISSUE-9999"), ("database_id", "999"),
    ("node_id", "wrong"), ("preimage_body_sha256", "0" * 64),
    ("preimage_managed_block_sha256", "0" * 64), ("postimage_body_sha256", "0" * 64),
    ("desired_managed_block_sha256", "0" * 64), ("protected_snapshot_sha256", "0" * 64),
    ("managed_field_deltas", ["Programme status"]),
])
def test_update_binding_tamper(prepared: dict[str, Any], field: str, value: Any) -> None:
    prepared["authority"]["payload"]["updates"][0][field] = value
    memory = Memory(prepared["remote"])
    with pytest.raises(ValueError):
        apply(prepared, memory)
    assert memory.writes == []


@pytest.mark.parametrize("field", [
    "plan_sha256", "remote_inventory_sha256", "claim_inventory_sha256", "registry_blob_sha256",
    "registry_blob_oid", "source_sha", "registry_path",
])
def test_batch_binding_tamper(prepared: dict[str, Any], field: str) -> None:
    prepared["authority"]["payload"][field] = "0" * 64
    memory = Memory(prepared["remote"])
    with pytest.raises(ValueError):
        apply(prepared, memory)
    assert not memory.writes


@pytest.mark.parametrize("field,value", [
    ("body", "caller body"), ("kind", "create"), ("kind", "close"), ("kind", "reopen"),
    ("title", "edited"), ("desired_state", "closed"), ("programme_status", "integrated"),
    ("blocking_dependencies", ["ISSUE-0008"]),
])
def test_plan_injection(prepared: dict[str, Any], field: str, value: Any) -> None:
    prepared["plan"]["actions"][0][field] = value
    resign(prepared["plan"])
    with pytest.raises(ValueError):
        gateway.managed_refresh_updates(prepared["registry"], prepared["plan"], prepared["remote"])


@pytest.mark.parametrize("transform", [
    lambda body: body.replace(sync.MANAGED_START, ""),
    lambda body: body + sync.MANAGED_END,
    lambda body: body.replace(sync.MANAGED_START, sync.LEGACY_MANAGED_START),
    lambda body: body + sync.LEGACY_MANAGED_END,
    lambda body: body.replace(sync.MANAGED_START, "TEMP_BOUNDARY").replace(sync.MANAGED_END, sync.MANAGED_START).replace("TEMP_BOUNDARY", sync.MANAGED_END),
    lambda body: body + "<!-- etf-ai-cockpit:stable-id=ISSUE-0001 -->",
    lambda body: body.replace("- Execution allowed: `false`", "- Execution allowed: `true`"),
    lambda body: body.replace("- Programme status: `planned`", "- Programme status: `integrated`"),
    lambda body: body.replace("- Blocking dependencies:", "- Owner: evil\n- Blocking dependencies:"),
])
def test_bad_boundaries_and_protected_lines(prepared: dict[str, Any], transform: Any) -> None:
    remote = copy.deepcopy(prepared["remote"])
    remote[0]["body"] = transform(remote[0]["body"])
    with pytest.raises(ValueError):
        plan = sync.plan_actions(prepared["registry"], remote)
        gateway.managed_refresh_updates(prepared["registry"], plan, remote)


@pytest.mark.parametrize("field,value", [
    ("title", "other"), ("state", "closed"), ("labels", ["changed"]),
    ("body", "stale body"), ("id", "12345"), ("node_id", "new"),
])
def test_stale_whole_batch_zero_writes(prepared: dict[str, Any], field: str, value: Any) -> None:
    memory = Memory(prepared["remote"])
    memory.remote[2][field] = value
    with pytest.raises(ValueError, match="stale_inventory"):
        apply(prepared, memory)
    assert not memory.writes


@pytest.mark.parametrize("failure,status,writes", [
    ("post", "applied_and_verified", [1, 2, 3]),
    ("pre", "write_failed_not_applied", [1, 2]),
    ("third", "conflict", [1, 2]), ("labels", "conflict", [1, 2]),
    ("comment", "conflict", [1, 2]),
    ("assignees", "conflict", [1, 2]), ("milestone", "conflict", [1, 2]),
])
def test_ambiguous_serial_stop_no_rollback(prepared: dict[str, Any], failure: str, status: str, writes: list[int]) -> None:
    memory = Memory(prepared["remote"], failure)
    result = apply(prepared, memory)
    assert result["terminal_status"] == status
    assert memory.writes == writes
    assert memory.remote[0]["body"] != prepared["remote"][0]["body"]


def test_remainder_exact_subset_and_reconciliation(prepared: dict[str, Any]) -> None:
    memory = Memory(prepared["remote"], "pre")
    assert not apply(prepared, memory)["accepted"]
    authority = prepared["authority"]
    pending = gateway.refresh_remainder_updates(authority, memory.remote)
    assert pending == authority["payload"]["updates"][1:]
    records = [prepared["bootstrap"], authority]
    assert not gateway.reconcile_authority_ledger(records, memory.remote)["accepted"]
    assert gateway.reconcile_authority_ledger(
        records, memory.remote, refresh_remainder_of=authority["authority_id"],
    )["accepted"]
    plan = sync.plan_actions(
        prepared["registry"], memory.remote, authority_records=records,
        authority_root=prepared["root"], refresh_remainder_of=authority["authority_id"],
    )
    candidate, ledger, _ = preparation.prepare(
        prepared["root"], plan, memory.remote, source_sha=prepared["head"],
        mode="managed_refresh", remainder_of_authority_id=authority["authority_id"],
    )
    assert candidate is None
    assert gateway.parse_authority_ledger(ledger)[-1]["payload"]["updates"] == pending
    memory.remote[2]["body"] += " conflict"
    with pytest.raises(ValueError, match="conflict"):
        gateway.refresh_remainder_updates(authority, memory.remote)


def test_zero_plan_no_authority_or_writes(prepared: dict[str, Any]) -> None:
    memory = Memory(prepared["remote"])
    apply(prepared, memory)
    plan = sync.plan_actions(prepared["registry"], memory.remote)
    assert gateway.managed_refresh_updates(prepared["registry"], plan, memory.remote) == []
    with pytest.raises(ValueError, match="zero_action"):
        preparation.prepare(prepared["root"], plan, memory.remote,
                            source_sha=prepared["head"], mode="managed_refresh")


def test_committed_remainder_applies_only_unapplied_rows(prepared: dict[str, Any]) -> None:
    memory = Memory(prepared["remote"], "pre")
    assert not apply(prepared, memory)["accepted"]
    original = prepared["authority"]
    records = [prepared["bootstrap"], original]
    plan = sync.plan_actions(
        prepared["registry"], memory.remote, authority_records=records,
        authority_root=prepared["root"], refresh_remainder_of=original["authority_id"],
    )
    _, ledger, _ = preparation.prepare(
        prepared["root"], plan, memory.remote, source_sha=prepared["head"],
        mode="managed_refresh", remainder_of_authority_id=original["authority_id"],
    )
    (prepared["root"] / gateway.AUTHORITY_PATH).write_bytes(ledger)
    git(prepared["root"], "add", ".")
    git(prepared["root"], "commit", "-qm", "reviewed remainder")
    source = prepared["head"]
    head = git(prepared["root"], "rev-parse", "HEAD")
    _, updated_records, binding = gateway.validate_authority_git_transition(
        prepared["root"], event_before=source, event_after=head, main_ref=None,
    )
    prepared.update(
        source=source, head=head, plan=plan, remote=copy.deepcopy(memory.remote),
        authority=updated_records[-1], binding=binding,
    )
    prepared["attestation"].update(event_before=source, event_after=head)
    remainder_memory = Memory(memory.remote)
    assert apply(prepared, remainder_memory)["accepted"]
    assert remainder_memory.writes == [2, 3]
    assert gateway.reconcile_authority_ledger(updated_records, remainder_memory.remote)["accepted"]


def test_existing_writer_dispatch_validation_and_oidc(prepared: dict[str, Any]) -> None:
    kwargs = dict(
        expected_parent=prepared["source"], expected_head=prepared["head"], main_ref=None,
        remote_reader=lambda: prepared["remote"],
    )
    completion.run(prepared["root"], prepared["root"] / "absent-candidate", apply=False, **kwargs)
    with pytest.raises(gateway.MutationPolicyError, match="github_actions_oidc_caller_proof_required"):
        completion.run(prepared["root"], prepared["root"] / "absent-candidate", apply=True,
                       **kwargs, **prepared["attestation"])


def test_writer_applies_and_independently_reads_back(prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    memory = Memory(prepared["remote"])
    calls = []
    monkeypatch.setattr(completion, "revalidate_live_authority", lambda *a, **kw: calls.append("revalidate"))
    evidence = prepared["root"].parent / "evidence.json"
    completion.run(
        prepared["root"], prepared["root"] / "absent-candidate", apply=True,
        expected_parent=prepared["source"], expected_head=prepared["head"], main_ref=None,
        remote_reader=memory.list_issues, mutation_transport=memory,
        caller_proof_verifier=lambda: calls.append("oidc"), evidence_out=evidence,
        **prepared["attestation"],
    )
    assert calls == ["oidc"] + ["revalidate"] * 7
    assert json.loads(evidence.read_text())["zero_action_readback"] is True
    assert memory.writes == [1, 2, 3]


def test_serial_claim_drift_stops_before_next_write(prepared: dict[str, Any]) -> None:
    memory = Memory(prepared["remote"])

    def revalidate() -> None:
        if memory.writes == [1]:
            duplicate = copy.deepcopy(memory.remote[1])
            duplicate["number"] = 99
            memory.remote.append(duplicate)

    result = gateway.apply_reviewed_managed_refresh(
        prepared["root"], prepared["plan"], prepared["remote"],
        authority_record=prepared["authority"], git_binding=prepared["binding"],
        attestation=prepared["attestation"], authority_revalidator=revalidate, transport=memory,
    )
    assert result["terminal_status"] == "stale_claim_inventory"
    assert memory.writes == [1]


@pytest.mark.parametrize("change", ["body", "execution", "duplicate", "extra_delta", "unsorted"])
def test_ledger_schema_rejects_expanded_capability(prepared: dict[str, Any], change: str) -> None:
    record = copy.deepcopy(prepared["authority"])
    if change == "body":
        record["payload"]["body"] = "injection"
    elif change == "execution":
        record["execution_allowed"] = True
    elif change == "duplicate":
        record["payload"]["updates"].append(record["payload"]["updates"][0])
    elif change == "extra_delta":
        record["payload"]["updates"][0]["managed_field_deltas"].append("Title")
    else:
        record["payload"]["updates"].reverse()
    record["authority_id"] = gateway._authority_id(record)
    with pytest.raises(ValueError):
        gateway.parse_authority_ledger(gateway.authority_ledger_bytes([prepared["bootstrap"], record]))


@pytest.mark.parametrize("field,value", [("execution_allowed", True), ("programme_status", "integrated"), ("title", "other")])
def test_registry_cannot_grant_protected_changes(prepared: dict[str, Any], field: str, value: Any) -> None:
    prepared["registry"]["records"][0][field] = value
    plan = sync.plan_actions(prepared["registry"], prepared["remote"])
    with pytest.raises(ValueError):
        gateway.managed_refresh_updates(prepared["registry"], plan, prepared["remote"])


def test_only_ledger_change(prepared: dict[str, Any]) -> None:
    (prepared["root"] / "unrelated").write_text("changed")
    git(prepared["root"], "add", ".")
    git(prepared["root"], "commit", "-qm", "unrelated")
    head = git(prepared["root"], "rev-parse", "HEAD")
    _, _, binding = gateway.validate_authority_git_transition(
        prepared["root"], event_before=prepared["source"], event_after=head, main_ref=None,
    )
    prepared["binding"] = binding
    prepared["attestation"]["event_after"] = head
    with pytest.raises(ValueError, match="ledger_only"):
        apply(prepared, Memory(prepared["remote"]))


def test_patch_primitive_body_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(gateway, "_run_gh", lambda args, **kw: calls.append((args, kw)))
    gateway.GhMutationTransport()._refresh_managed_body(7, "body")
    assert len(calls) == 1
    assert "PATCH" in calls[0][0]
    assert json.loads(calls[0][1]["input_text"]) == {"body": "body"}
    source = Path(gateway.__file__).read_text()
    assert source.count("client._refresh_managed_body(") == 1


@pytest.mark.parametrize("field,value", [
    ("assignees", [{"id": 99, "node_id": "USER_99", "login": "another"}]),
    ("milestone", None),
])
def test_refresh_metadata_preflight_is_whole_batch(
    prepared: dict[str, Any], field: str, value: Any,
) -> None:
    memory = Memory(prepared["remote"])
    memory.remote[2][field] = value
    with pytest.raises(gateway.MutationPolicyError, match="stale_protected_snapshot") as caught:
        apply(prepared, memory)
    assert memory.writes == []
    assert caught.value.evidence["updates"] == []
    assert caught.value.evidence["failure_phase"] == "inventory_read"


@pytest.mark.parametrize("field,value", [("assignees", []), ("milestone", None)])
def test_refresh_metadata_reconciliation_and_planning_reject_drift(
    prepared: dict[str, Any], field: str, value: Any,
) -> None:
    memory = Memory(prepared["remote"])
    assert apply(prepared, memory)["accepted"]
    memory.remote[0][field] = value
    authorities = [prepared["bootstrap"], prepared["authority"]]
    assert gateway.reconcile_authority_ledger(authorities, memory.remote)["error"] == "managed_refresh_projection_mismatch"
    plan = sync.plan_actions(prepared["registry"], memory.remote, authority_records=authorities)
    assert plan["summary"]["blocked"] > 0


def test_refresh_metadata_does_not_reinterpret_historical_hashes(prepared: dict[str, Any]) -> None:
    stripped = copy.deepcopy(prepared["remote"])
    for row in stripped:
        row.pop("assignees")
        row.pop("milestone")
    assert sync.inventory_sha256(stripped) == sync.inventory_sha256(prepared["remote"])
    assert gateway.claim_inventory_sha256(stripped) == gateway.claim_inventory_sha256(prepared["remote"])
    assert gateway.snapshot_evidence(stripped[0]) == gateway.snapshot_evidence(prepared["remote"][0])
    assert sync.plan_actions(prepared["registry"], stripped) == sync.plan_actions(prepared["registry"], prepared["remote"])
    normalized = sync.normalise_remote_issue(prepared["remote"][0], include_refresh_protected=True)
    assert normalized["assignees"] == [{"id": "10", "node_id": "USER_10", "login": "owner"}]
    assert normalized["milestone"]["id"] == "20"
    assert gateway.refresh_protected_sha256(normalized) == gateway.refresh_protected_sha256(prepared["remote"][0])
    assert gateway.refresh_protected_sha256(stripped[0]) != gateway.refresh_protected_sha256(normalized)


def test_authority_revoked_during_prefetch_prevents_patch(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = Memory(prepared["remote"])
    original_fetch = memory.fetch_issue
    first_issue_reads = 0
    revoked = False

    def fetch(number: int) -> dict[str, Any]:
        nonlocal first_issue_reads, revoked
        if number == 1:
            first_issue_reads += 1
            if first_issue_reads == 2:
                revoked = True
        return original_fetch(number)

    def revalidate() -> None:
        if revoked:
            raise RuntimeError("authority revoked during prefetch")

    monkeypatch.setattr(memory, "fetch_issue", fetch)
    with pytest.raises(gateway.MutationPolicyError) as caught:
        gateway.apply_reviewed_managed_refresh(
            prepared["root"], prepared["plan"], prepared["remote"],
            authority_record=prepared["authority"], git_binding=prepared["binding"],
            attestation=prepared["attestation"], authority_revalidator=revalidate, transport=memory,
        )
    assert revoked
    assert memory.writes == []
    assert caught.value.evidence["failure_phase"] == "prewrite_authority"
    assert caught.value.evidence["updates"] == []


@pytest.mark.parametrize("failure,phase", [
    ("authority", "prefetch_authority"), ("list", "claim_inventory_read"),
    ("fetch", "preimage_read"),
])
def test_outer_writer_preserves_progress_after_operation_failure(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch, failure: str, phase: str,
) -> None:
    memory = Memory(prepared["remote"])
    original_list, original_fetch = memory.list_issues, memory.fetch_issue

    def revalidate(*args: Any, **kwargs: Any) -> None:
        if failure == "authority" and memory.writes == [1]:
            raise RuntimeError("authority unavailable")

    def list_issues() -> list[dict[str, Any]]:
        if failure == "list" and memory.writes == [1]:
            raise RuntimeError("inventory unavailable")
        return original_list()

    def fetch(number: int) -> dict[str, Any]:
        if failure == "fetch" and memory.writes == [1] and number == 2:
            raise RuntimeError("issue unavailable")
        return original_fetch(number)

    monkeypatch.setattr(completion, "revalidate_live_authority", revalidate)
    monkeypatch.setattr(memory, "list_issues", list_issues)
    monkeypatch.setattr(memory, "fetch_issue", fetch)
    evidence_path = prepared["root"].parent / "failed-evidence.json"
    with pytest.raises(gateway.MutationTransportError) as caught:
        completion.run(
            prepared["root"], prepared["root"] / "absent-candidate", apply=True,
            expected_parent=prepared["source"], expected_head=prepared["head"], main_ref=None,
            remote_reader=memory.list_issues, mutation_transport=memory,
            caller_proof_verifier=lambda: None, evidence_out=evidence_path,
            **prepared["attestation"],
        )
    first = prepared["authority"]["payload"]["updates"][0]
    assert memory.writes == [1]
    evidence = caught.value.evidence
    assert evidence["accepted"] is False
    assert evidence["terminal_status"] == "operation_failed"
    assert evidence["failure_phase"] == phase
    assert evidence["failure_issue_number"] == 2
    assert evidence["updates"] == [{
        "issue_number": 1, "stable_id": "ISSUE-0001", "observation": "post", "write_error": False,
        "preimage_body_sha256": first["preimage_body_sha256"],
        "postimage_body_sha256": first["postimage_body_sha256"],
        "observed_body_sha256": first["postimage_body_sha256"],
        "observed_protected_snapshot_sha256": first["protected_snapshot_sha256"],
    }]
    assert json.loads(evidence_path.read_text())["mutation"] == evidence


def test_preflight_transport_failure_also_carries_evidence(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = Memory(prepared["remote"])

    def unavailable() -> list[dict[str, Any]]:
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(memory, "list_issues", unavailable)
    with pytest.raises(gateway.MutationPolicyError) as caught:
        apply(prepared, memory)
    assert memory.writes == []
    assert caught.value.evidence["updates"] == []
    assert caught.value.evidence["failure_phase"] == "inventory_read"
