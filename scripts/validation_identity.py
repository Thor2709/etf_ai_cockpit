"""Shared protected identity paths for classification and terminal evidence.

Expanding this binding invalidates old evidence; it never rewrites that evidence.
Volatile personal configuration and historical observations are not policy.
"""
from __future__ import annotations

DEFAULT_ARTIFACT_MANIFEST = ".github/issue-transitions/protected-evidence-manifest.json"
DURABLE_HARNESS_PATHS = (
    ".agents/agents",
    "docs/codex-config/config-core.toml",
    "docs/codex-config/agents",
    "docs/codex-config/global-AGENTS.md",
    "docs/codex-config/README.md",
    "docs/codex-config/agent_routing.py",
    "docs/codex-config/agy_delegate.py",
    "docs/codex-config/enforce-agent-routing.ps1",
    "docs/codex-config/codex-skills",
    "docs/development/CONTROL_PLANE.md",
    "docs/architecture/decisions/ADR-0008-control-plane-observation-and-authority.md",
    "plans/ACTIVE_CODEX_GOAL.md",
    "plans/BATCH-B04-ANALYSIS-SPINE.md",
    "PLAN_step2.md",
)


def identity_groups(artifact_manifest: str = DEFAULT_ARTIFACT_MANIFEST) -> dict[str, tuple[str, ...]]:
    """Return fresh mappings; callers cannot mutate another consumer's policy."""
    environment = (
        "pyproject.toml", "requirements.txt", "requirements-dev.txt",
        "requirements-release.txt", "requirements-release-parsers.txt",
        "requirements-github-mutation-runtime.txt", ".python-version",
        "uv.lock", "poetry.lock", "pdm.lock",
    )
    return {
        "environment": environment,
        "source": ("src", "scripts", "tests", "docs/codex-config/test_agy_delegate.py",
                   "docs/codex-config/test_agent_routing.py"),
        "dependency": environment,
        "product_tree": ("src", "configs"),
        "policy": (
            "AGENTS.md", ".gitattributes", ".gitignore", ".github/workflows", "configs", "packaging",
            "docs/product-completion/DELIVERY_WORKFLOW.md",
            artifact_manifest, *DURABLE_HARNESS_PATHS,
        ),
    }
