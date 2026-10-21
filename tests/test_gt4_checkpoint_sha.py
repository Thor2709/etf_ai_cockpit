"""GT4: a rewritten weight file must never keep the previous checkpoint identity."""

import os

from etf_cockpit.models import local_weights
from etf_cockpit.models.local_weights import checkpoint_content_sha


def _checkpoint(tmp_path, payload: bytes):
    directory = tmp_path / "ckpt"
    directory.mkdir(exist_ok=True)
    (directory / "config.json").write_text("{}", encoding="utf-8")
    weights = directory / "model.safetensors"
    weights.write_bytes(payload)
    return directory, weights


def test_same_size_rewrite_with_identical_timestamp_changes_the_sha(tmp_path) -> None:
    directory, weights = _checkpoint(tmp_path, b"weights-v1")
    stamp = weights.stat().st_mtime_ns
    first = checkpoint_content_sha(directory)

    weights.write_bytes(b"weights-v2")
    os.utime(weights, ns=(stamp, stamp))  # coarse-granularity filesystems: same size and same mtime

    assert checkpoint_content_sha(directory) != first


def test_settled_weights_are_hashed_once(tmp_path, monkeypatch) -> None:
    directory, weights = _checkpoint(tmp_path, b"weights-v1")
    old = weights.stat().st_mtime_ns - 3600 * 10**9
    os.utime(weights, ns=(old, old))
    os.utime(directory / "config.json", ns=(old, old))
    local_weights._CHECKPOINT_SHA_CACHE.clear()
    first = checkpoint_content_sha(directory)
    monkeypatch.setattr(local_weights.hashlib, "sha256", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("rehashed")))

    assert checkpoint_content_sha(directory) == first
