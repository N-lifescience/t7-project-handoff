import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

PACKAGE = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, PACKAGE / 'scripts' / (name + '.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


h = module('handoff')
installer = module('install')


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.scope = self.base / 'Projects'
        self.scope.mkdir()
        self.root = self.scope / '공백 있는 프로젝트'
        self.root.mkdir()
        self.runtime = self.base / 'runtime'

    def tearDown(self):
        self.temp.cleanup()

    def event(self, name, session='first', **fields):
        payload = {'cwd': str(self.root), 'session_id': session, 'hook_event_name': name, **fields}
        return h.hook(payload, 'codex', self.scope, self.runtime)

    def checkpoint(self, path):
        path.parent.mkdir(exist_ok=True)
        head = h.git(self.root, 'rev-parse', 'HEAD').decode().strip() or 'non-git'
        text = (f'# Task: Fix the project\nStatus: in-progress\nUpdated: 2026-10-05T12:00:00+09:00\n'
                f'Branch: main\nHEAD: {head}\n\n')
        text += '\n'.join(f'## {title}\nObserved result for {title}.\n' for title in h.SECTIONS)
        path.write_text(text)
        self.assertEqual(h.seal(path, self.root), [])

    def current_note(self):
        # The injected path is deliberately obtained from observable hook output.
        result = self.event('SessionStart')
        context = result['hookSpecificOutput']['additionalContext']
        return Path(context.split('Your checkpoint: ', 1)[1].split('. After meaningful', 1)[0])

    def test_outside_scope_does_not_write_or_inject(self):
        result = h.hook({'cwd': str(self.base), 'session_id': 'x', 'hook_event_name': 'SessionStart'},
                        'codex', self.scope, self.runtime)
        self.assertIsNone(result)
        self.assertFalse(self.runtime.exists())
        self.assertFalse((self.base / '.handoff').exists())

    def test_casual_turn_does_not_require_checkpoint(self):
        self.event('SessionStart')
        self.event('UserPromptSubmit')
        self.assertIsNone(self.event('Stop'))
        self.assertFalse((self.root / '.handoff').exists())

    def test_missing_checkpoint_requests_one_continuation(self):
        self.event('SessionStart')
        (self.root / 'app.py').write_text('changed')
        result = self.event('Stop')
        self.assertEqual(result['decision'], 'block')
        second = self.event('Stop')
        self.assertNotIn('decision', second)
        self.assertIn('incomplete', second['systemMessage'])

    def test_valid_current_checkpoint_allows_stop(self):
        note = self.current_note()
        (self.root / 'app.py').write_text('changed')
        self.checkpoint(note)
        self.assertIsNone(self.event('Stop'))

    def test_source_delete_after_checkpoint_is_detected(self):
        source = self.root / 'app.py'
        source.write_text('before')
        note = self.current_note()
        source.write_text('changed')
        self.checkpoint(note)
        source.unlink()
        result = self.event('Stop')
        self.assertEqual(result['decision'], 'block')
        self.assertIn('current project state', result['reason'])

    def test_sessions_have_distinct_notes(self):
        a = self.event('SessionStart', session='a')['hookSpecificOutput']['additionalContext']
        b = self.event('SessionStart', session='b')['hookSpecificOutput']['additionalContext']
        self.assertNotEqual(a, b)
        self.assertEqual(len(list(self.runtime.glob('*.json'))), 2)

    def test_compaction_preserves_turn_baseline(self):
        self.event('SessionStart')
        (self.root / 'app.py').write_text('changed')
        self.event('SessionStart', source='compact')
        self.assertEqual(self.event('Stop')['decision'], 'block')

    def test_other_stop_hook_cannot_cause_a_loop(self):
        self.event('SessionStart')
        (self.root / 'app.py').write_text('changed')
        self.assertNotIn('decision', self.event('Stop', stop_hook_active=True))

    def test_new_user_turn_resets_reminder(self):
        self.event('SessionStart')
        source = self.root / 'app.py'
        source.write_text('one')
        self.assertEqual(self.event('Stop')['decision'], 'block')
        self.event('UserPromptSubmit')
        source.write_text('two')
        self.assertEqual(self.event('Stop')['decision'], 'block')

    def test_generated_and_checkpoint_changes_do_not_trigger(self):
        self.event('SessionStart')
        for name in ('node_modules', '.handoff', 'dist'):
            folder = self.root / name
            folder.mkdir()
            (folder / 'example.txt').write_text('generated')
        self.assertIsNone(self.event('Stop'))

    def test_placeholder_and_large_notes_are_rejected(self):
        note = self.current_note()
        self.checkpoint(note)
        note.write_text(note.read_text().replace('Observed result for Next.', '...'))
        self.assertIn('unfinished Next', h.validate(note, self.root))
        note.write_text('x' * 8001)
        self.assertIn('exceeds', h.validate(note)[0])

    def test_git_dirty_file_changes_and_commits(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for key, value in [('user.name', 'Test'), ('user.email', 'test@example.invalid')]:
            subprocess.run(['git', '-C', str(self.root), 'config', key, value], check=True)
        source = self.root / 'app.py'
        source.write_text('initial')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'commit', '-qm', 'initial'], check=True)
        source.write_text('dirty before turn')
        note = self.current_note()
        source.write_text('dirty after turn')
        self.assertEqual(self.event('Stop')['decision'], 'block')
        self.checkpoint(note)
        self.assertIsNone(self.event('Stop'))
        subprocess.run(['git', '-C', str(self.root), 'add', 'app.py'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'commit', '-qm', 'change'], check=True)
        self.assertIn('HEAD does not match the working repository', h.validate(note, self.root))
        outside = self.base / 'linked-worktree'
        subprocess.run(['git', '-C', str(self.root), 'worktree', 'add', '-qb', 'test-worktree', str(outside)],
                       check=True, stdout=subprocess.DEVNULL)
        self.assertEqual(h.project(outside, self.scope), outside.resolve())

    def test_list_is_bounded_and_searches_titles(self):
        note = self.current_note()
        self.checkpoint(note)
        self.assertEqual(len(h.notes(self.root, limit=1)), 1)
        self.assertEqual(h.notes(self.root, query='unrelated'), [])
        self.assertEqual(len(h.notes(self.root, query='FIX')), 1)

    def old_completed_notes(self, count=25):
        directory = self.root / '.handoff'
        directory.mkdir(exist_ok=True)
        for index in range(count):
            path = directory / ('done-' + str(index) + '.md')
            path.write_text(f'# Task: Completed task {index}\nStatus: done\n')
            old = time.time() - (31 + index) * 86400
            os.utime(path, (old, old))
        active = directory / 'active.md'
        active.write_text('# Task: Ongoing work\nStatus: in-progress\n')
        old = time.time() - 100 * 86400
        os.utime(active, (old, old))

    def test_archive_keeps_recent_completed_and_all_active_notes(self):
        self.old_completed_notes()
        moved = h.archive_completed(self.root, apply=True)
        self.assertEqual(len(moved), 5)
        self.assertEqual(len(list((self.root / '.handoff').glob('done-*.md'))), 20)
        self.assertTrue((self.root / '.handoff/active.md').exists())
        self.assertEqual(len(list((self.root / '.handoff/archive').glob('*.md'))), 5)
        self.assertTrue(h.notes(self.root, query='task 24')[0].startswith('archive/'))

    def test_archive_preview_does_not_move_or_create_directories(self):
        self.old_completed_notes()
        self.assertEqual(len(h.archive_completed(self.root)), 5)
        self.assertFalse((self.root / '.handoff/archive').exists())
        self.assertEqual(len(list((self.root / '.handoff').glob('done-*.md'))), 25)

    def test_archive_preserves_current_session_note_and_fresh_notes(self):
        self.old_completed_notes()
        protected = self.root / '.handoff/done-24.md'
        fresh = self.root / '.handoff/done-23.md'
        fresh.touch()
        h.archive_completed(self.root, apply=True, protected=protected)
        self.assertTrue(protected.exists())
        self.assertTrue(fresh.exists())

    def test_install_preserves_existing_rules_hooks_and_symlink(self):
        codex, claude, agents = [self.base / x for x in ('codex', 'claude', 'agents')]
        codex.mkdir(); claude.mkdir()
        original = '기존 지침을 보존합니다.\n'
        (codex / 'AGENTS.md').write_text(original)
        parent = self.scope / 'old-rules.md'
        parent.write_text(original)
        (self.scope / 'CLAUDE.md').symlink_to(parent)
        prior = {'permissions': {'allow': ['Read']}, 'hooks': {'Stop': [{'hooks': [
            {'type': 'command', 'command': 'existing-guard', 'timeout': 10}]}]}}
        (claude / 'settings.json').write_text(json.dumps(prior))
        (codex / 'hooks.json').write_text(json.dumps({'hooks': prior['hooks']}))
        target, items = installer.build_plan(PACKAGE, self.scope, codex, claude, agents)
        installer.apply_plan(target, items)
        self.assertTrue((self.scope / 'CLAUDE.md').is_symlink())
        self.assertTrue(parent.read_text().startswith(original))
        after = json.loads((claude / 'settings.json').read_text())
        self.assertEqual(after['permissions'], prior['permissions'])
        self.assertEqual(after['hooks']['Stop'][0], prior['hooks']['Stop'][0])
        self.assertTrue((agents / 'skills/project-handoff').is_symlink())
        _, again = installer.build_plan(PACKAGE, self.scope, codex, claude, agents)
        self.assertEqual(again, [])
        installer.uninstall(self.scope, codex, claude, agents)
        self.assertEqual(parent.read_text(), original)
        self.assertEqual((codex / 'AGENTS.md').read_text(), original)
        final = json.loads((claude / 'settings.json').read_text())
        self.assertEqual(final, prior)
        self.assertFalse((agents / 'skills/project-handoff').is_symlink())

    def test_install_aborts_if_configuration_changed_after_plan(self):
        codex, claude, agents = [self.base / x for x in ('codex', 'claude', 'agents')]
        codex.mkdir(); claude.mkdir()
        path = codex / 'AGENTS.md'
        path.write_text('original\n')
        target, items = installer.build_plan(PACKAGE, self.scope, codex, claude, agents)
        path.write_text('another session changed this\n')
        with self.assertRaises(ValueError):
            installer.apply_plan(target, items)
        self.assertEqual(path.read_text(), 'another session changed this\n')
        self.assertFalse((claude / 'settings.json').exists())
        self.assertFalse((target / 'SKILL.md').exists())


if __name__ == '__main__':
    unittest.main()
