# Codex root orchestration rules

Mandatory for Codex root sessions (moved out of `AGENTS.md` so Claude sessions, which do not use
the V2 roles, do not load it on every request). The rules are unchanged.

## Authority and routing

Codex root alone accepts work, commits/pushes, controls PRs/merges, mutates
canonical programme state and synchronises GitHub. The twelve named V2 roles,
models and efforts are defined in `docs/codex-config/agents/`, the durable
`config-core.toml`, and checked by `agent_routing.py`; machine snapshots are not
proof of the live runtime. Use the matching named role, verify actual child
role/model/effort metadata, and preserve required independent reviewer,
risk-reviewer and release-verifier gates. Never substitute a worker/self-review
for a required formal role. Fallback is only for tasks with no matching role;
record the exception. Children cannot spawn children or integrate.

After spawning a formal V2 child, run `python scripts/v2_runtime_attestation.py`
with its exact canonical `--agent-path` and expected configured `--expected-role`,
`--expected-model`, `--expected-effort`, actual runtime `--expected-cwd` and
`--codex-home` before consuming its work. Successful persisted attestation is
required; requested role/TOML and child self-report are not runtime proof.
Ambiguous, contradictory or unavailable evidence fails closed.

Use one useful child normally, usually no more than two; a third needs an
already-required, dependency-ready, disjoint assignment whose result will be
consumed. The configured hard ceiling is headroom, not a target. Required
reviewers take priority; promptly release completed children. On a thread-limit
failure release completed children and retry the exact role once. An unresolved
residency failure requires preserving the exact checkpoint, not weakening review.

AGY Scout/Editor are subordinate external capabilities, not V2 roles. Derive
capability states from `agy_delegate.py`. Scout uses the reviewed read-only
fresh-project route. Editor uses only a disposable exact-base worktree and
whole-candidate promotion; never direct authoritative-worktree editing. Reject
the entire candidate for any forbidden/unowned change. Codex independently
inspects every promoted byte and decides test sufficiency. Hooks are diagnostic,
not preventive containment. Normal V2 is fallback; legacy independent AGY lanes
are historical candidates, never active programme reservations. The reviewed
Skill source does not establish live installation: verify local hashes.
