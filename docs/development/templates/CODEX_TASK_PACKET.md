# ETF AI Cockpit — compact Codex task packet

Use this template for one bounded assignment. Do not paste the full repository rules or backlog; Codex loads the applicable AGENTS chain separately.

## Outcome

Describe one observable completed state. Begin with the result, not a proposed algorithm.

## Identity

- Issue/train:
- Exact base SHA:
- Branch/worktree:
- Expected validation tier:
- Parent/dependency commits already integrated:

## Read first

Read only:

1. applicable global/root/nested `AGENTS.md`;
2. the selected issue and acceptance criteria;
3. the named source symbols and focused tests;
4. a named SDD/ADR only when the contract changes.

Do not load the whole registry, all historical plans or unrelated backlog.

## Evidence of the current gap

- Reproduction/observation:
- Expected:
- Actual:
- Exact command/test/log:
- What is fact versus inference:

## Ownership

### May write

- paths/symbols:

### May read

- paths/symbols:

### Must not change

- paths/contracts/authority:

### Other active lanes

- lane + ownership:

## Hard invariants

List only task-specific invariants not already stated in AGENTS.

## Done when

- product behaviour:
- failure/unavailable behaviour:
- tests:
- documentation/ADR:
- generated/canonical evidence:
- exact output/handoff:

## Verification

Run focused evidence first. Broaden only when the impact tool, classifier, review finding or repository contract requires it.

## Stop conditions

Stop and return evidence when:

- requirement or identity is ambiguous;
- write ownership overlaps another lane;
- an unexpected architecture/migration/authority decision appears;
- two attempts do not materially improve evidence;
- protected external authority is required.

## Return format

```text
STATUS:
BASE/HEAD:
OWNERSHIP:
CHANGES:
EVIDENCE:
REMAINING UNCERTAINTY:
NEXT ACTION:
```
