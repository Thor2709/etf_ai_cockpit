"""Read-only routing audit and explicitly scoped generated-policy updates."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tomllib

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--owned-worktree', action='append', default=[])
    args = parser.parse_args()
    if args.owned_worktree and not args.apply:
        parser.error('--owned-worktree requires --apply')
    if args.apply and not args.owned_worktree:
        parser.error('--apply requires explicit --owned-worktree paths')
    here = Path(__file__).resolve().parent
    repo = here.parent.parent
    codex = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    problems = []
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
