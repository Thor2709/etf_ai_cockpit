# ETF AI Cockpit — operating rules

## Start from evidence, not chronology

Fetch `origin/main`, verify the remote is `Thor2709/etf_ai_cockpit`, and leave
unrelated dirty checkouts untouched. Read this file and
`docs/development/CONTROL_PLANE.md`. From a clean exact-main checkout run:

```text
python scripts/programme_execution.py --check
python scripts/programme_execution.py --issue <selected-ID>
```

The first command derives current/next work, blockers, ownership and evidence
availability. It cannot fetch GitHub, launch workers, accept work or mutate the
programme. Supply reconciled local lane/PR observations before parallel work.
Select from canonical readiness AND lifecycle eligibility. Verify existing
implementation before writing new code. Read only selected source/tests; do not
remap the repository or load historical archives by default.

## Non-negotiable boundaries

Keep the application local-first and `execution_allowed=false`. Do not enable
live orders, add broker/provider writes, upload silently, deploy, publish
releases/tags or force-push. Do not fabricate financial evidence or zero-fill
missing data. Preserve adjusted/corporate-action-aware returns, point-in-time,
revision, replay, provenance, privacy and security semantics; no look-ahead or
survivorship leakage. Risk/data-quality gates override forecasts, models and UI
actions. Optional model packages/weights remain disabled-safe with deterministic
baselines. Keep UI separate from domain calculations and one canonical path per
financial calculation. Do not add production dependencies without explicit
authority or weaken tests/acceptance to obtain green validation.

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

## Delivery

Define the outcome, issue criteria, owned files/tests/runtime resources and
invariants before delegation. One writer per overlapping boundary, including
AGY. Separate worktrees alone are not independence. Root serialises canonical
writes and merges; ownership records are observations, not distributed locks.

Follow `docs/product-completion/DELIVERY_WORKFLOW.md` for exact-head E/O/H/C
validation, legal product/lifecycle ordering and evidence reuse. Programme-control,
harness, financial, persistence, concurrency, security and release changes need
required independent reviews and full Linux/Windows packaged gates. Freeze a
clean complete head, collect all required verdicts, consolidate valid findings,
and run only attributable evidence before freezing a replacement. Never accept
stale-head CI. Do not rerun unchanged valid evidence merely because a session or
review ended. Use one watcher; terminal `validation-summary` is the normal CI
interface. A passing job or mergeable PR is not final acceptance.

Edit semantic sources through the existing authority process, then run atomic
`generate_programme.py` and a second byte-clean `--check`. Never hand-edit rendered
registry/status views. A product merge is not canonical completion; where the
ancestry guard requires it, follow with the single reviewed lifecycle transaction
and independent zero-action readback. No speculative gateway expansion, retries
of ambiguous writes, compensation or history rewriting.

Standing owner authority covers bounded in-scope local repairs, not protected
external actions. Resolve instruction conflicts by preserving the stronger safety
invariant. After two failed attempts without improved evidence, record the exact
failure, attempts and next decision; do not loop or change unrelated code.
Update the relevant SDD/ADR for architecture/contract changes. Report concrete
findings, exact identities, tests, reviews, gates, merges and blockers.
