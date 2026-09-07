"""Restricted official AGY entry point; standard library, no credential access.

Protocol: https://www.antigravity.google/docs/cli/headless/
Custom agents: https://www.antigravity.google/docs/subagents/
Unknown protocol/tool surfaces fail closed pending a reviewed live fixture.
"""
from __future__ import annotations

import argparse
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
CAPABILITY_STATES = {'codex-flash-scout': 'disabled', 'codex-flash-editor': 'disabled'}
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


def require_fresh_containment(agent, diagnostic_log=''):
    """No proven positive fresh-headless identity/hook artifact exists in 1.1.27.

    These observed negative diagnostics are useful evidence, but their absence,
    init.agent, and a nonzero hook count cannot establish preventive containment.
    There is deliberately no caller-supplied boolean or state-switch bypass.
    """
    if re.search(r'Agent .* not found, falling back to default', diagnostic_log):
        raise CapabilityDisabled(f'{agent}: custom-agent fallback observed')
    if 'loaded 0 named hooks from 0 hooks.json file(s)' in diagnostic_log:
        raise CapabilityDisabled(f'{agent}: required hooks were not loaded')
    raise CapabilityDisabled(f'{agent}: fresh headless agent and hook identity unproven')


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


def parse_stream(stdout, cwd, model, agent):
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
        require(step.get('state') in ('ACTIVE', 'DONE'), 'Invalid step state')
        kind = step.get('step_type')
        require(kind in ('user_input', 'agent_response', 'tool', 'checkpoint'), 'Unknown step type')
        if 'subagent_info' in step:
            raise CapabilityDisabled('Subagent activity')
        if kind == 'tool' or 'tool_name' in step or 'tool_info' in step:
            name = step.get('tool_name')
            if isinstance(name, str) and name not in AGENTS[agent]:
                raise CapabilityDisabled('Forbidden tool activity; containment unproven')
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
    require(not re.search(r'denied', result.stderr, re.I),
            'AGY diagnostic reports a denied action')
    require(not re.search(r'permission', result.stderr, re.I),
            'AGY diagnostic reports a permission condition')
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
    version = run_cli(executable, ['--version'], workspace, 30)
    versions = re.findall(r'(?<![\w.])(\d+)\.(\d+)\.(\d+)(?![\w.-])', version)
    require(len(versions) == 1 and tuple(map(int, versions[0])) >= (1, 1, 27), 'AGY version must be >=1.1.27')
    listing = run_cli(executable, ['models'], workspace, 30)
    require(model in re.findall(r'[A-Za-z0-9_.-]+', listing), 'Expected models entry unavailable')
    # The listing is discovery only. init.agent echoes the requested agent even
    # on fallback; neither establishes actual custom-agent or hook activation.
    run_cli(executable, ['agents'], workspace, 30)
    args = ['-p', prompt, '--output-format', 'stream-json', '--model', model, '--agent', agent,
            '--print-timeout', f'{timeout}s', '--sandbox', '--json-schema', json.dumps(HANDOFF_SCHEMA)]
    if agent == 'codex-flash-scout':
        args.extend(['--mode', 'plan'])
    return parse_stream(run_cli(executable, args, workspace, timeout + 5), workspace, model, agent)


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
