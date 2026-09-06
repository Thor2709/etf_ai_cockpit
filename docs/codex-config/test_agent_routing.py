"""Focused regressions; all writes are confined to temporary fixtures."""
import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('agent_routing', HERE / 'agent_routing.py')
routing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routing)
VALID = (HERE / 'config-core.toml').read_text(encoding='utf-8')


class TomlAuditTests(unittest.TestCase):
    def test_canonical_templates_pass(self):
        for filename in ('config.toml', 'config-core.toml'):
            with self.subTest(filename=filename):
                self.assertEqual([], routing.validate_config(routing.read_toml(HERE / filename)))

    def test_wrong_table_controls_fail(self):
        for section, assignment in (
            ('agents', 'max_concurrent_threads_per_session = 6'),
            ('features', 'multi_agent_v2 = true'),
            ('agents', 'default_subagent_model = "gpt-5.6-luna"'),
            ('agents', 'default_subagent_reasoning_effort = "high"'),
        ):
            with self.subTest(assignment=assignment):
                changed = VALID.replace(assignment, '') + '\n[unrelated]\n' + assignment
                problems = routing.validate_config(tomllib.loads(changed))
                self.assertTrue(any('must be' in problem for problem in problems))
                self.assertTrue(any('wrong table' in problem for problem in problems))

    def test_wrong_root_model_scope_fails(self):
        changed = VALID.replace('model = "gpt-6-astra"', '') + '\n[unrelated]\nmodel = "gpt-6-astra"\n'
        self.assertIn("model must be 'gpt-6-astra'.", routing.validate_config(tomllib.loads(changed)))

    def test_invalid_toml_and_duplicate_scopes_fail(self):
        for suffix in ('\n[agents]\n', '\n[features]\n', '\n[broken\n', '\nwindows = {x = 1, x = 2}\n'):
            with self.subTest(suffix=suffix):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'invalid.toml'
                    path.write_text(VALID + suffix, encoding='utf-8')
                    with self.assertRaises(tomllib.TOMLDecodeError):
                        routing.read_toml(path)

    def test_duplicate_key_fails(self):
        with self.assertRaises(tomllib.TOMLDecodeError):
            tomllib.loads(VALID.replace('[agents]', '[agents]\nmax_concurrent_threads_per_session = 6'))

    def test_fallback_and_control_types_are_enforced(self):
        for original, replacement in (
            ('default_subagent_model = "gpt-5.6-luna"', 'default_subagent_model = "gpt-5.6-sol"'),
            ('default_subagent_reasoning_effort = "high"', 'default_subagent_reasoning_effort = "low"'),
            ('max_concurrent_threads_per_session = 6', 'max_concurrent_threads_per_session = "6"'),
            ('multi_agent_v2 = true', 'multi_agent_v2 = "true"'),
        ):
            with self.subTest(replacement=replacement):
                self.assertTrue(routing.validate_config(tomllib.loads(VALID.replace(original, replacement))))

    def test_legacy_alias_and_extra_wrong_scope_fail(self):
        for assignment in ('max_threads = 6', 'max_concurrent_threads_per_session = 6', 'multi_agent_v2 = true'):
            with self.subTest(assignment=assignment):
                self.assertTrue(routing.validate_config(tomllib.loads(VALID + '\n[unrelated]\n' + assignment)))

    def test_comments_and_multiline_strings_are_not_controls(self):
        text = 'note = """\n[agents]\nmax_threads = 2\n"""\n' + VALID
        text = text.replace('multi_agent_v2 = true', 'multi_agent_v2 = true # enabled')
        self.assertEqual([], routing.validate_config(tomllib.loads(text)))


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        self.repo.mkdir()
        (self.repo / 'AGENTS.md').write_bytes(b'canonical policy\n')
        self.owned = Path(self.temp.name) / 'owned'
        self.other = Path(self.temp.name) / 'antigravity-candidate'
        for path in (self.owned, self.other):
            path.mkdir()
            (path / 'AGENTS.md').write_bytes(b'old policy\n')
        self.registered = [self.repo, self.owned, self.other]

    def test_no_selection_refused_without_writes(self):
        with self.assertRaisesRegex(ValueError, 'explicit'):
            routing.apply_overrides(self.repo, [], self.registered)
        self.assertFalse((self.owned / 'AGENTS.override.md').exists())

    def test_only_selected_worktree_written_and_generated_override_can_update(self):
        untouched = self.other / 'AGENTS.override.md'
        untouched.write_bytes(b'handwritten other policy\n')
        self.assertEqual(1, routing.apply_overrides(self.repo, [self.owned], self.registered))
        target = self.owned / 'AGENTS.override.md'
        self.assertTrue(target.read_bytes().startswith(routing.MARKER.encode()))
        self.assertTrue(target.read_bytes().endswith(b'canonical policy\n'))
        (self.repo / 'AGENTS.md').write_bytes(b'updated policy\n')
        routing.apply_overrides(self.repo, [self.owned], self.registered)
        self.assertTrue(target.read_bytes().endswith(b'updated policy\n'))
        self.assertEqual(b'handwritten other policy\n', untouched.read_bytes())

    def test_unmarked_override_rejects_entire_selection_before_write(self):
        handwritten = self.other / 'AGENTS.override.md'
        handwritten.write_bytes(b'owned by someone else\n')
        with self.assertRaisesRegex(ValueError, 'unmarked'):
            routing.apply_overrides(self.repo, [self.owned, self.other], self.registered)
        self.assertFalse((self.owned / 'AGENTS.override.md').exists())
        self.assertEqual(b'owned by someone else\n', handwritten.read_bytes())

    def test_unregistered_selection_refused(self):
        with self.assertRaisesRegex(ValueError, 'registered'):
            routing.apply_overrides(self.repo, [self.owned], [self.repo])
        self.assertFalse((self.owned / 'AGENTS.override.md').exists())

    def test_canonical_policy_does_not_delete_existing_override(self):
        override = self.repo / 'AGENTS.override.md'
        content = routing.MARKER.encode() + b'\nexisting override\n'
        override.write_bytes(content)
        self.assertEqual(0, routing.apply_overrides(self.repo, [self.repo], self.registered))
        self.assertEqual(content, override.read_bytes())


if __name__ == '__main__':
    unittest.main()
