"""Restricted official AGY entry point; standard library, no credential access.

Protocol: https://www.antigravity.google/docs/cli/headless/
Custom agents: https://www.antigravity.google/docs/subagents/
Unknown protocol/tool surfaces fail closed pending a reviewed live fixture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

READ_TOOLS = frozenset({'view_file', 'grep_search', 'find_by_name', 'list_dir'})
EDIT_TOOLS = READ_TOOLS | {'write_to_file', 'replace_file_content', 'multi_replace_file_content'}
AGENTS = {'codex-flash-scout': READ_TOOLS, 'codex-flash-editor': EDIT_TOOLS}
DEFAULT_MODEL = 'gemini-3.8-flash-medium'
MODELS = {DEFAULT_MODEL, 'gemini-3.8-flash-high'}
CAPABILITY_STATES = {'codex-flash-scout': 'shadow', 'codex-flash-editor': 'disabled'}
STATES = frozenset({'disabled', 'shadow', 'enabled'})
LIST_FIELDS = ('files_inspected', 'requirements_addressed', 'candidate_tests', 'uncertainties')
HANDOFF_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'assignment_status': {'type': 'string', 'enum': ['complete', 'partial', 'blocked']},
        **{key: {'type': 'array', 'items': {'type': 'string'}} for key in LIST_FIELDS},
        'recommended_next_action': {'type': 'string'},
    },
    'required': ['assignment_status', *LIST_FIELDS, 'recommended_next_action'],
}
REPO = Path(__file__).resolve().parents[2]


class DelegationError(ValueError):
    """Rejected run; never infer acceptance from a worker response."""


class CapabilityDisabled(DelegationError):
    """Containment failure: this capability needs a reviewed repair."""


class RunDegraded(DelegationError):
    """This assignment was denied safely; use V2 fallback for this run."""


def require_fresh_containment(agent):
    """Only the evidenced fresh-project read-only scout route is eligible."""
    if agent != 'codex-flash-scout':
        raise CapabilityDisabled(f'{agent}: editor containment unproven')


def workspace_snapshot(workspace):
    """Require a clean Git root and fingerprint all files, including ignored files.

    Git metadata is represented by HEAD/status, not read as workspace content.
    Refuse reparse points instead of following them outside the owned boundary.
    """
    def git(*args):
        try:
            result = subprocess.run(
                ['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', *args],
                cwd=str(workspace), capture_output=True, text=True, encoding='utf-8',
                errors='strict', timeout=30, stdin=subprocess.DEVNULL, shell=False)
        except (OSError, UnicodeError, subprocess.SubprocessError) as error:
            raise DelegationError('Cannot verify workspace Git state') from error
        require(result.returncode == 0, 'Cannot verify workspace Git state')
        return result.stdout

    require(Path(git('rev-parse', '--show-toplevel').strip()).resolve() == workspace,
            'Workspace must be the exact Git root')
    head = git('rev-parse', '--verify', 'HEAD').strip()
    require(not git('status', '--porcelain=v1', '--untracked-files=all'), 'Workspace Git state is dirty')
    files = {}
    def unreadable(error):
        raise error

    for directory, dirs, names in os.walk(workspace, followlinks=False, onerror=unreadable):
        parent = Path(directory)
        if parent == workspace and '.git' in dirs:
            dirs.remove('.git')
        for name in dirs + names:
            path = parent / name
            metadata = path.lstat()
            require(not path.is_symlink() and not getattr(metadata, 'st_file_attributes', 0) & 0x400,
                    'Workspace contains a reparse point')
            digest = None
            if path.is_file():
                with path.open('rb') as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
            else:
                require(path.is_dir(), 'Unsupported workspace filesystem entry')
            files[path.relative_to(workspace).as_posix()] = (metadata.st_mode, metadata.st_mtime_ns, digest)
    return head, files


def require(condition, message):
    if not condition:
        raise DelegationError(message)


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON field')
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, 'Nonfinite JSON'))
    except (ValueError, TypeError) as error:
        raise DelegationError('Malformed JSON') from error


def agent_path(repo, name):
    return repo / '.agents' / 'agents' / name / 'agent.md'


def validate_agent(path, name):
    """Validate our deliberately small JSON-valued YAML subset without PyYAML."""
    text = path.read_text(encoding='utf-8')
    parts = text.split('---', 2)
    require(len(parts) == 3 and not parts[0].strip(), 'Missing agent frontmatter')
    config = {}
    for line in parts[1].splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(':')
        require(separator and key not in config, 'Invalid agent frontmatter')
        config[key] = strict_json(value)
    expected = {
        'name': name, 'mainAgent': True, 'subagent': False, 'model': 'flash',
        'commandExecutionPolicy': 'off', 'inheritCustomizations': False,
        'mcpServers': [], 'skills': [], 'plugins': [],
    }
    require(set(config) == set(expected) | {'description', 'tools'}, 'Unexpected agent settings')
    for key, value in expected.items():
        require(type(config[key]) is type(value) and config[key] == value,
                f'Unsafe agent setting: {key}')
    tools = config['tools']
    require(isinstance(tools, list) and all(isinstance(x, str) for x in tools)
            and len(tools) == len(AGENTS[name]) and set(tools) == AGENTS[name], 'Unsafe agent tools')
    require(isinstance(config['description'], str) and config['description'].strip()
            and parts[2].strip(), 'Missing agent instructions')


def validate_handoff(value):
    require(isinstance(value, dict) and set(value) == set(HANDOFF_SCHEMA['required']),
            'Unexpected handoff fields')
    require(value['assignment_status'] in ('complete', 'partial', 'blocked'), 'Invalid assignment status')
    for key in LIST_FIELDS:
        require(isinstance(value[key], list) and all(isinstance(x, str) for x in value[key]),
                f'Invalid handoff list: {key}')
    require(isinstance(value['recommended_next_action'], str), 'Invalid next action')
    return value


def has_denials(value):
    denied = False
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'denied_actions':
                require(isinstance(item, list) or type(item) is int and item >= 0,
                        'Malformed denied actions')
                denied |= bool(item)
            denied |= has_denials(item)
    elif isinstance(value, list):
        for item in value:
            denied |= has_denials(item)
    return denied


def parse_stream(stdout, cwd, model, agent, *, unchanged=False):
    events = [strict_json(line) for line in stdout.splitlines() if line.strip()]
    require(len(events) >= 2 and all(isinstance(x, dict) for x in events), 'Missing stream events')
    require(events[0].get('event') == 'init' and events[-1].get('event') == 'result', 'Invalid stream order')
    init = events[0].get('init')
    require(isinstance(init, dict), 'Missing init')
    require(isinstance(init.get('cwd'), str) and Path(init['cwd']).is_absolute()
            and Path(init['cwd']).resolve() == cwd, 'Wrong init cwd')
    require(init.get('model') == model and init.get('agent') == agent, 'Wrong init model/agent')
    require(init.get('permission_mode') == 'request-review', 'Unsafe permission mode')
    exposed = init.get('tools')
    require(isinstance(exposed, list) and all(isinstance(x, str) for x in exposed)
            and len(exposed) == len(set(exposed)), 'Malformed or missing tool registry')
    conversation = events[0].get('conversation_id')
    require(isinstance(conversation, str) and bool(conversation), 'Missing conversation identity')
    used = set()
    denied = False
    for event in events:
        denied |= has_denials(event)
    for event in events[1:-1]:
        require(event.get('event') == 'step_update', 'Unexpected stream event')
        step = event.get('step_update')
        require(isinstance(step, dict) and step.get('conversation_id') == conversation, 'Wrong step identity')
        require(step.get('state') in ('ACTIVE', 'DONE', 'ERROR'), 'Invalid step state')
        kind = step.get('step_type')
        require(kind in ('user_input', 'agent_response', 'tool', 'checkpoint'), 'Unknown step type')
        if 'subagent_info' in step:
            raise CapabilityDisabled('Subagent activity')
        if kind == 'tool' or 'tool_name' in step or 'tool_info' in step:
            name = step.get('tool_name')
            require(kind == 'tool' and isinstance(name, str), 'Invalid tool use')
            if isinstance(name, str) and name not in AGENTS[agent]:
                info = step.get('tool_info')
                require(isinstance(info, dict) and info.get('name', name) == name,
                        'Inconsistent forbidden tool identity')
                if step['state'] == 'ERROR':
                    error = info.get('error')
                    if not (isinstance(error, dict) and error.get('type') == 'TOOL_ERROR'
                            and error.get('message') == f'unknown tool: "{name}" — check spelling'):
                        raise CapabilityDisabled('Forbidden tool error does not prove capability absence')
                    require(unchanged, 'Forbidden error lacks clean-state evidence')
                    denied = True
                    continue
                if step['state'] == 'ACTIVE':
                    # An attempt is not an effect; require a terminal error below.
                    terminal = [x.get('step_update', {}) for x in events[1:-1]
                                if x.get('step_update', {}).get('step_index') == step.get('step_index')
                                and x.get('step_update', {}).get('tool_name') == name]
                    if any(x.get('state') == 'DONE' for x in terminal):
                        raise CapabilityDisabled('Forbidden tool executed')
                    require(step.get('step_index') is not None and terminal[-1].get('state') == 'ERROR',
                            'Forbidden attempt lacks terminal denial')
                    continue
                raise CapabilityDisabled('Forbidden tool executed')
            require(kind == 'tool' and isinstance(name, str) and name in exposed, 'Invalid tool use')
            info = step.get('tool_info', {})
            require(isinstance(info, dict) and info.get('name', name) == name
                    and not info.get('error'), 'Failed or inconsistent tool call')
            parameters = info.get('parameters')
            require(isinstance(parameters, dict), 'Missing tool parameters')
            path_fields = {
                'view_file': 'AbsolutePath', 'write_to_file': 'TargetFile',
                'replace_file_content': 'TargetFile',
                'multi_replace_file_content': 'TargetFile', 'list_dir': 'DirectoryPath',
                'find_by_name': 'SearchDirectory', 'grep_search': 'SearchPath',
            }
            path_value = parameters.get(path_fields[name])
            require(isinstance(path_value, str) and Path(path_value).is_absolute(),
                    'Missing absolute tool path')
            resolved_path = Path(path_value).resolve(strict=False)
            require(resolved_path == cwd or cwd in resolved_path.parents,
                    'Tool path escapes workspace')
            used.add(name)
    result = events[-1].get('result')
    require(isinstance(result, dict) and result.get('conversation_id') == conversation, 'Wrong result identity')
    require(result.get('status') == 'SUCCESS' and not result.get('error'), 'Unsuccessful terminal result')
    for key, expected in (('model', model), ('agent', agent)):
        require(key not in result or result[key] == expected, f'Wrong result {key}')
    if 'cwd' in result:
        require(isinstance(result['cwd'], str) and Path(result['cwd']).is_absolute()
                and Path(result['cwd']).resolve() == cwd, 'Wrong result cwd')
    handoff = validate_handoff(result.get('structured_output'))
    if denied:
        raise RunDegraded('Denied actions: assignment degraded; use V2 fallback')
    return {'cwd': str(cwd), 'model': model, 'agent': agent, 'status': 'SUCCESS',
            'init_tools': exposed, 'tools_used': sorted(used), 'denied_actions': [], 'handoff': handoff}


def run_cli(executable, args, cwd, timeout):
    try:
        result = subprocess.run([executable, *args], cwd=str(cwd), capture_output=True,
                                text=True, encoding='utf-8', errors='strict', timeout=timeout,
                                stdin=subprocess.DEVNULL, shell=False)
    except subprocess.TimeoutExpired as error:
        raise DelegationError('AGY timeout; inspect any real diff and use V2 fallback') from error
    except (OSError, UnicodeError) as error:
        raise DelegationError('AGY could not run or output was not UTF-8') from error
    require(result.returncode == 0, 'AGY process failed; check CLI availability/auth interactively')
    # Diagnostics are captured but not echoed: they may contain local sensitive data.
    require(not re.search(r'authentication required', result.stderr, re.I),
            'AGY diagnostic reports authentication required')
    # Hook/permission prose is diagnostic, not a tool effect or safe-denial
    # proof. Structured events plus the independent workspace check decide.
    return result.stdout


def delegate(cwd, agent, prompt, timeout=180, model=DEFAULT_MODEL, high_reason=None):
    workspace = Path(cwd)
    require(workspace.is_absolute() and workspace.is_dir(), 'Explicit existing absolute cwd required')
    workspace = workspace.resolve(strict=True)
    require(agent in AGENTS and model in MODELS, 'Unsupported agent/model; use V2 fallback')
    require(model == DEFAULT_MODEL or isinstance(high_reason, str) and high_reason.strip(),
            'High requires explicit root justification')
    require(type(timeout) is int and 1 <= timeout <= 600, 'Timeout must be 1..600 seconds')
    require(isinstance(prompt, str) and prompt.strip(), 'Empty task packet')
    state = CAPABILITY_STATES.get(agent)
    require(state in STATES, 'Invalid capability state')
    if state == 'disabled':
        raise CapabilityDisabled(f'{agent}: capability disabled')
    require_fresh_containment(agent)
    for variable in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS',
                     'GOOGLE_GENAI_USE_VERTEXAI'):
        require(not os.environ.get(variable), 'Provider override present; do not change auth route')
    for name in AGENTS:
        source = agent_path(REPO, name)
        target = agent_path(workspace, name)
        validate_agent(source, name)
        require(not target.is_symlink() and target.read_bytes() == source.read_bytes(),
                'Workspace custom agent differs from reviewed source')
    executable = shutil.which('agy')
    if executable is None and os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        installed = Path(os.environ['LOCALAPPDATA']) / 'agy' / 'bin' / 'agy.exe'
        if installed.is_file():
            executable = str(installed)
    require(executable is not None, 'Official agy is unavailable; use V2 fallback')
    require(Path(executable).suffix.lower() not in ('.bat', '.cmd', '.ps1'), 'AGY shell shim unsupported')
    before = workspace_snapshot(workspace)
    try:
        stdout = run_scout(executable, workspace, agent, prompt, timeout, model)
    finally:
        try:
            after = workspace_snapshot(workspace)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise CapabilityDisabled('Post-run workspace cleanliness could not be verified') from error
        if after != before:
            raise CapabilityDisabled('Scout changed workspace or Git state')
    return parse_stream(stdout, workspace, model, agent, unchanged=True)


def run_scout(executable, workspace, agent, prompt, timeout, model):
    version = run_cli(executable, ['--version'], workspace, 30)
    versions = re.findall(r'(?<![\w.])(\d+)\.(\d+)\.(\d+)(?![\w.-])', version)
    require(len(versions) == 1 and versions[0] == ('1', '1', '27'), 'AGY version must be exactly 1.1.27')
    listing = run_cli(executable, ['models'], workspace, 30)
    require(model in re.findall(r'[A-Za-z0-9_.-]+', listing), 'Expected models entry unavailable')
    # The listing is discovery only. init.agent echoes the requested agent even
    # on fallback; neither establishes actual custom-agent or hook activation.
    run_cli(executable, ['agents'], workspace, 30)
    args = ['-p', prompt, '--output-format', 'stream-json', '--model', model, '--agent', agent,
            '--print-timeout', f'{timeout}s', '--sandbox', '--new-project', '--add-dir', str(workspace),
            '--json-schema', json.dumps(HANDOFF_SCHEMA)]
    if agent == 'codex-flash-scout':
        args.extend(['--mode', 'plan'])
    return run_cli(executable, args, workspace, timeout + 5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--agent', required=True, choices=sorted(AGENTS))
    parser.add_argument('--packet', required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--model', default=DEFAULT_MODEL, choices=sorted(MODELS))
    parser.add_argument('--high-reason')
    args = parser.parse_args()
    try:
        result = delegate(args.cwd, args.agent, args.packet.read_text(encoding='utf-8'),
                          args.timeout, args.model, args.high_reason)
    except (OSError, ValueError) as error:
        status = ('CAPABILITY_DISABLED' if isinstance(error, CapabilityDisabled) else
                  'RUN_DEGRADED' if isinstance(error, RunDegraded) else 'REJECTED')
        print(json.dumps({'status': status, 'reason': str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
