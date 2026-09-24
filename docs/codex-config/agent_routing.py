"""Read-only routing audit and explicitly scoped generated-policy updates."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tomllib

import agy_delegate

MARKER = '<!-- generated-by: docs/codex-config/enforce-agent-routing.ps1 -->'
EXPECTED = {
    'benchmark_guard': ('gpt-5.6-luna', 'high'),
    'diagnostician': ('gpt-6-astra', 'medium'),
    'documentation_maintainer': ('gpt-5.6-luna', 'high'),
    'documentation_researcher': ('gpt-5.6-luna', 'high'),
    'implementer': ('gpt-6-astra', 'low'),
    'performance_refactorer': ('gpt-6-astra', 'low'),
    'planner': ('gpt-5.6-sol', 'medium'),
    'release_verifier': ('gpt-5.6-sol', 'medium'),
    'reviewer': ('gpt-6-astra', 'low'),
    'risk_reviewer': ('gpt-6-astra', 'medium'),
    'scout': ('gpt-5.6-luna', 'high'),
    'test_engineer': ('gpt-5.6-sol', 'medium'),
}


def read_toml(path):
    with Path(path).open('rb') as stream:
        return tomllib.load(stream)


def validate_external_workers(repo):
    """Separate external-worker audit; never extend the twelve-role EXPECTED."""
    problems = []
    if (repo / '.agents/skills/antigravity-flash').exists():
        problems.append('Codex AGY skill must not appear in repository .agents/skills.')
    definitions = set((repo / '.agents/agents').glob('codex-flash-*/agent.md'))
    expected_paths = {agy_delegate.agent_path(repo, name) for name in agy_delegate.AGENTS}
    if definitions != expected_paths or list((repo / '.agents/agents').glob('codex-flash-*.md')):
        problems.append('Exactly two canonical external-worker definitions are required.')
    for name in agy_delegate.AGENTS:
        try:
            agy_delegate.validate_agent(agy_delegate.agent_path(repo, name), name)
        except (OSError, ValueError) as error:
            problems.append(f'{name}: {error}')
    workflow = (repo / 'docs/product-completion/DELIVERY_WORKFLOW.md').read_text(encoding='utf-8')
    if re.search(r'\b(?:ten|10)[ -]+child(?:ren)?\b', workflow, re.I):
        problems.append('Delivery workflow retains obsolete capacity authority.')
    # These are protected contract clauses, not semantic interpretation of prose.
    contract = ' '.join(workflow.split())
    for clause in (
        'AGY editors count as writers under the same file/runtime ownership limits.',
        'They have no canonical programme-state authority, cannot satisfy formal V2 '
        'reviewer/risk/release gates and cannot decide validation sufficiency.',
    ):
        if clause not in contract:
            problems.append('Missing protected external-worker authority clause.')
    for path in expected_paths | set((repo / 'docs/codex-config/codex-skills/antigravity-flash').rglob('*.md')):
        if path.exists() and '--dangerously-' + 'skip-permissions' in path.read_text(encoding='utf-8'):
            problems.append(f'Permission bypass forbidden in worker/skill: {path}')
    return problems


def validate_config(data):
    expected = {
        ('model',): 'gpt-6-astra',
        ('model_reasoning_effort',): 'low',
        ('plan_mode_reasoning_effort',): 'medium',
        ('agents', 'max_concurrent_threads_per_session'): 6,
        ('agents', 'default_subagent_model'): 'gpt-5.6-luna',
        ('agents', 'default_subagent_reasoning_effort'): 'high',
        ('features', 'multi_agent_v2'): True,
    }
    problems = []
    for keys, value in expected.items():
        actual = data
        for key in keys:
            actual = actual.get(key) if isinstance(actual, dict) else None
        if type(actual) is not type(value) or actual != value:
            problems.append(f'{".".join(keys)} must be {value!r}.')
    # These controls have one authoritative scope; reject aliases elsewhere too.
    scopes = {keys[-1]: keys for keys in expected if len(keys) == 2}
    def inspect(node, prefix=()):
        if isinstance(node, dict):
            for key, value in node.items():
                location = prefix + (key,)
                if key == 'max_threads':
                    problems.append('Legacy max_threads is forbidden.')
                if key in scopes and location != scopes[key]:
                    problems.append(f'{".".join(location)} is in the wrong table.')
                inspect(value, location)
        elif isinstance(node, list):
            for value in node:
                inspect(value, prefix)
    inspect(data)
    return problems


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def registered_worktrees(repo):
    records = git(repo, 'worktree', 'list', '--porcelain', '-z').split(b'\0')
    return [Path(os.fsdecode(record[9:])).resolve() for record in records
            if record.startswith(b'worktree ')]


def apply_overrides(repo, selected, registered):
    if not selected:
        raise ValueError('Apply requires explicit -OwnedWorktree paths.')
    canonical = (repo / 'AGENTS.md').read_bytes()
    digest = hashlib.sha256(canonical).hexdigest().upper()
    content = (MARKER + f'\n<!-- canonical-sha256: {digest} -->\n').encode() + canonical
    targets = []
    for supplied in selected:
        worktree = Path(supplied).resolve(strict=True)
        if worktree not in registered:
            raise ValueError(f'Not a registered worktree: {worktree}')
        override = worktree / 'AGENTS.override.md'
        if override.is_symlink():
            raise ValueError(f'Refusing symlink override: {override}')
        if override.exists() and override.read_bytes().splitlines()[:1] != [MARKER.encode()]:
            raise ValueError(f'Refusing unmarked override: {override}')
        policy = worktree / 'AGENTS.md'
        if not policy.exists() or policy.read_bytes() != canonical:
            targets.append(override)
    # Preflight every selection before writing. Never delete existing overrides.
    for override in targets:
        override.write_bytes(content)
    return len(targets)


def validate_source_templates(repo):
    """Audit reviewed repository sources without asserting a live installation."""
    here = repo / 'docs/codex-config'
    problems = validate_external_workers(repo)
    for path in (here / 'config.toml', here / 'config-core.toml'):
        try:
            problems.extend(f'{path}: {problem}' for problem in validate_config(read_toml(path)))
        except (OSError, ValueError) as error:
            problems.append(f'{path}: {error}')
    for role, expected in EXPECTED.items():
        try:
            data = read_toml(here / 'agents' / f'{role}.toml')
            if (data.get('model'), data.get('model_reasoning_effort')) != expected:
                problems.append(f'{role}: reviewed role differs from routing matrix')
        except (OSError, ValueError) as error:
            problems.append(f'{role}: {error}')
    for relative in ('AGENTS.md', 'plans/ACTIVE_CODEX_GOAL.md',
                     'plans/BATCH-B04-ANALYSIS-SPINE.md',
                     'docs/codex-config/README.md',
                     'docs/product-completion/DELIVERY_WORKFLOW.md',
                     'docs/development/CONTROL_PLANE.md',
                     'docs/codex-config/codex-skills/antigravity-flash/SKILL.md'):
        path = repo / relative
        if not path.is_file():
            problems.append(f'Missing current instruction surface: {relative}')
            continue
        text = ' '.join(path.read_text(encoding='utf-8').split())
        for short, agent in (('scout', 'codex-flash-scout'), ('editor', 'codex-flash-editor')):
            current = agy_delegate.CAPABILITY_STATES[agent]
            for state in ('enabled', 'disabled', 'shadow'):
                if state != current and re.search(r'\b' + short + r' (?:is|remains) ' + state + r'\b', text, re.I):
                    problems.append(f'Contradictory {short} state in {relative}')
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--source-only', action='store_true', help='validate repository sources, not personal/live configuration')
    parser.add_argument('--owned-worktree', action='append', default=[])
    args = parser.parse_args()
    if args.source_only and (args.apply or args.owned_worktree):
        parser.error('--source-only cannot write worktree overrides')
    if args.owned_worktree and not args.apply:
        parser.error('--owned-worktree requires --apply')
    if args.apply and not args.owned_worktree:
        parser.error('--apply requires explicit --owned-worktree paths')
    here = Path(__file__).resolve().parent
    repo = here.parent.parent
    codex = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    problems = validate_source_templates(repo)
    if args.source_only:
        if problems:
            raise ValueError('\n'.join(problems))
        print('Reviewed source routing and current instruction audit passed; live runtime unverified.')
        return
    for path in (codex / 'config.toml', here / 'config.toml', here / 'config-core.toml'):
        try:
            problems.extend(f'{path}: {problem}' for problem in validate_config(read_toml(path)))
        except (OSError, ValueError) as error:
            problems.append(f'{path}: {error}')
    for role, expected in EXPECTED.items():
        path = codex / 'agents' / f'{role}.toml'
        try:
            data = read_toml(path)
            if (data.get('model'), data.get('model_reasoning_effort')) != expected:
                problems.append(f'{role}: expected {expected[0]}/{expected[1]}.')
        except (OSError, ValueError) as error:
            problems.append(f'{path}: {error}')
    if problems:
        raise ValueError('\n'.join(problems))
    worktrees = registered_worktrees(repo)
    applied = apply_overrides(repo, args.owned_worktree, worktrees) if args.apply else 0
    print(f'Routing audit passed; registered worktrees: {len(worktrees)}; overrides written: {applied}.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
