from __future__ import annotations

from pathlib import Path

import yaml


def _valid_registry_payload() -> dict:
    return {
        "schema_version": "1.0",
        "registry_id": "test-registry",
        "policy_version": "wave0-task4",
        "last_reviewed": "2026-07-12",
        "execution_allowed": False,
        "executable_authority": False,
        "rejections": [
            {
                "rejection_id": "TEST-1",
                "status": "permanent",
                "scope": "test-scope",
                "decision_owner": "governance",
                "rationale": "test rationale",
                "created_at": "2026-07-12",
                "reviewed_at": "2026-07-12",
                "evidence_refs": ["docs/evidence.md"],
                "execution_allowed": False,
                "executable_authority": False,
            }
        ],
    }


def _load_registry(root: Path):
    try:
        from etf_cockpit.governance.static_checks import load_rejection_registry
    except ImportError:
        return None
    return load_rejection_registry(root)


def test_rejection_registry_is_versioned_auditable_duplicate_free_and_non_executable() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = _load_registry(root)
    assert registry is not None
    assert registry["schema_version"] == "1.0"
    assert registry["execution_allowed"] is False
    records = registry["rejections"]
    ids = [record["rejection_id"] for record in records]
    assert ids and len(ids) == len(set(ids))
    for record in records:
        assert record["status"] == "permanent"
        assert record["execution_allowed"] is False
        assert record["executable_authority"] is False
        assert record["decision_owner"]
        assert record["rationale"]
        assert record["created_at"]
        assert record["evidence_refs"]


def test_rejection_registry_validation_rejects_duplicate_ids_and_true_authority(tmp_path: Path) -> None:
    config = tmp_path / "rejection_registry.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "execution_allowed": False,
                "rejections": [
                    {
                        "rejection_id": "DUP-1",
                        "status": "permanent",
                        "decision_owner": "governance",
                        "rationale": "test",
                        "created_at": "2026-07-12",
                        "evidence_refs": ["test"],
                        "execution_allowed": False,
                        "executable_authority": False,
                    },
                    {
                        "rejection_id": "DUP-1",
                        "status": "permanent",
                        "decision_owner": "governance",
                        "rationale": "test",
                        "created_at": "2026-07-12",
                        "evidence_refs": ["test"],
                        "execution_allowed": True,
                        "executable_authority": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        from etf_cockpit.governance.static_checks import validate_rejection_registry
    except ImportError:
        validate_rejection_registry = None
    if validate_rejection_registry is None:
        assert False, "rejection registry validator is not implemented"
    errors = validate_rejection_registry(config)
    assert "duplicate rejection_id" in " ".join(errors)
    assert "execution_allowed" in " ".join(errors)


def test_registry_validator_rejects_top_level_authority_and_missing_audit_schema() -> None:
    try:
        from etf_cockpit.governance.static_checks import validate_rejection_registry
    except ImportError:
        validate_rejection_registry = None
    if validate_rejection_registry is None:
        assert False, "rejection registry validator is not implemented"

    payload = {
        "schema_version": "1.0",
        "execution_allowed": False,
        "executable_authority": True,
        "rejections": [
            {
                "rejection_id": "TEST-1",
                "status": "permanent",
                "decision_owner": "governance",
                "rationale": "test rationale",
                "created_at": "2026-07-12",
                "evidence_refs": ["docs/evidence.md"],
                "execution_allowed": False,
                "executable_authority": False,
            }
        ],
    }
    errors = validate_rejection_registry(payload)
    joined = " ".join(errors)
    assert "executable_authority" in joined
    for field_name in ("registry_id", "policy_version", "last_reviewed", "scope", "reviewed_at"):
        assert field_name in joined


def test_registry_validator_rejects_empty_and_non_string_evidence_refs() -> None:
    try:
        from etf_cockpit.governance.static_checks import validate_rejection_registry
    except ImportError:
        validate_rejection_registry = None
    if validate_rejection_registry is None:
        assert False, "rejection registry validator is not implemented"

    payload = _valid_registry_payload()
    payload["rejections"][0]["evidence_refs"] = ["", "   ", 42]
    errors = validate_rejection_registry(payload)
    assert "evidence_refs" in " ".join(errors)


def test_registry_validator_rejects_missing_evidence_paths_when_loaded_from_file(tmp_path: Path) -> None:
    try:
        from etf_cockpit.governance.static_checks import validate_rejection_registry
    except ImportError:
        validate_rejection_registry = None
    if validate_rejection_registry is None:
        assert False, "rejection registry validator is not implemented"

    payload = _valid_registry_payload()
    payload["rejections"][0]["evidence_refs"] = ["missing-evidence.md#section"]
    config = tmp_path / "configs" / "rejection_registry.yaml"
    config.parent.mkdir()
    config.write_text(yaml.safe_dump(payload), encoding="utf-8")
    errors = validate_rejection_registry(config)
    assert "path does not exist" in " ".join(errors)
