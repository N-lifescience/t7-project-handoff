#!/usr/bin/env python3
"""Install T7-scoped instructions, skill entrypoints, and local lifecycle hooks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import sys
import time

BEGIN = '<!-- BEGIN:t7-project-handoff -->'
END = '<!-- END:t7-project-handoff -->'
PACKAGE_FILES = ('SKILL.md', 'RULES.md', '.gitignore', '사용안내.md',
                 'scripts/handoff.py', 'scripts/install.py', 'tests/test_handoff.py')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_data(path):
    return path.read_bytes() if path.exists() else None


def block(scope, target):
    return (f'{BEGIN}\n## T7 project checkpoints\n\n'
            f'When working under `{scope}` or in a Git worktree linked to a repository there, '
            f'follow `{target / "RULES.md"}`. Save a short session checkpoint after meaningful '
            'progress and before the substantive final reply; resume from the relevant short note. '
            'The `project-handoff` skill provides the format. This rule applies only to T7 Projects.\n'
            f'{END}')


def append_block(data, text):
    old = data.decode('utf-8') if data is not None else ''
    if BEGIN in old:
        if END not in old or old.count(BEGIN) != 1 or old.count(END) != 1:
            raise ValueError('Malformed existing managed block')
        start, end = old.index(BEGIN), old.index(END) + len(END)
        return (old[:start] + text + old[end:]).encode()
    separator = '\n' if old.endswith('\n') else '\n\n' if old else ''
    return (old + separator + text + '\n').encode()


def add_hooks(data, target, backend):
    obj = json.loads(data) if data else {}
    hooks = obj.setdefault('hooks', {})
    quoted = shlex.quote(str(target / 'scripts/handoff.py'))
    command = f'if [ -f {quoted} ]; then /usr/bin/python3 {quoted} hook --backend {backend}; fi'
    for event in ('SessionStart', 'UserPromptSubmit', 'Stop'):
        groups = hooks.setdefault(event, [])
        # Idempotent without changing handlers installed by Paseo or another tool.
        for group in groups:
            group['hooks'] = [h for h in group.get('hooks', [])
                              if str(target / 'scripts/handoff.py') not in h.get('command', '')]
        groups[:] = [g for g in groups if g.get('hooks')]
        handler = {'type': 'command', 'command': command, 'timeout': 8}
        if backend == 'codex' and event != 'Stop':
            handler['additionalContextLimit'] = 700
        groups.append({'hooks': [handler]})
    return (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode()


def build_plan(source, scope, codex, claude, agents):
    scope = scope.resolve()
    target = scope / '_workspace-rules/project-handoff'
    if not scope.is_dir():
        raise ValueError('Projects root is unavailable: ' + str(scope))
    items = []

    def write(path, data):
        # Preserve existing symlinks such as Projects/CLAUDE.md.
        actual = path.resolve() if path.is_symlink() else path
        before = file_data(actual)
        if before != data:
            items.append({'path': str(actual), 'kind': 'file', 'before': before, 'after': data})

    for relative in PACKAGE_FILES:
        src = source / relative
        if not src.is_file():
            raise ValueError('Missing package file: ' + str(src))
        destination = target / relative
        if destination.exists() and not (target / 'SKILL.md').exists():
            raise ValueError('Unrecognized existing installation: ' + str(target))
        write(destination, src.read_bytes())
    codex_guidance = codex / ('AGENTS.override.md' if (codex / 'AGENTS.override.md').is_file()
                             and (codex / 'AGENTS.override.md').stat().st_size else 'AGENTS.md')
    for path in (codex_guidance, scope / 'CLAUDE.md'):
        write(path, append_block(file_data(path), block(scope, target)))
    for path, backend in ((codex / 'hooks.json', 'codex'), (claude / 'settings.json', 'claude')):
        write(path, add_hooks(file_data(path), target, backend))
    for path in (agents / 'skills/project-handoff', claude / 'skills/project-handoff'):
        if path.is_symlink() and path.resolve() == target:
            continue
        if path.exists() or path.is_symlink():
            raise ValueError('Skill entrypoint already occupied: ' + str(path))
        items.append({'path': str(path), 'kind': 'symlink', 'target': str(target)})
    return target, items


def atomic_write(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.handoff-' + secrets.token_hex(4))
    try:
        with temporary.open('xb') as handle:
            handle.write(value)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_plan(target, items):
    if not items:
        return {'changed': 0, 'target': str(target), 'message': 'Already installed.'}
    backup = target / '.install-backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup, 0o700)
    atomic_write(backup.parent / '.gitignore', b'*\n')
    applied, journal = [], []
    try:
        for index, item in enumerate(items):
            path = Path(item['path'])
            entry = {k: v for k, v in item.items() if k not in ('before', 'after')}
            if item['kind'] == 'file':
                if file_data(path) != item['before']:
                    raise ValueError('File changed since plan: ' + str(path))
                entry['before_sha256'] = digest(item['before']) if item['before'] is not None else None
                entry['after_sha256'] = digest(item['after'])
                entry['mode'] = path.stat().st_mode & 0o777 if path.exists() else 0o600
                if item['before'] is not None:
                    saved = backup / (str(index) + '.before')
                    atomic_write(saved, item['before'])
                    entry['backup'] = str(saved)
                journal.append(entry)
                atomic_write(backup / 'journal.json', (json.dumps(journal, indent=2) + '\n').encode())
                atomic_write(path, item['after'], entry['mode'])
            else:
                if path.exists() or path.is_symlink():
                    raise ValueError('Skill entrypoint changed since plan: ' + str(path))
                journal.append(entry)
                atomic_write(backup / 'journal.json', (json.dumps(journal, indent=2) + '\n').encode())
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(item['target'], target_is_directory=True)
            applied.append((item, entry))
    except BaseException:
        for item, entry in reversed(applied):
            path = Path(item['path'])
            if item['kind'] == 'symlink':
                if path.is_symlink() and str(path.readlink()) == item['target']:
                    path.unlink()
            elif file_data(path) == item['after']:
                if item['before'] is None:
                    path.unlink()
                else:
                    atomic_write(path, item['before'], entry['mode'])
        raise
    receipt = {'changed': len(items), 'target': str(target), 'backup': str(backup),
               'paths': [x['path'] for x in items],
               'activation': 'Restart sessions; review the three new Codex handlers in /hooks. No hook trust was bypassed.'}
    atomic_write(target / 'installation-receipt.json', (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode())
    return receipt


def uninstall(scope, codex, claude, agents):
    target = scope.resolve() / '_workspace-rules/project-handoff'
    changed = []
    for path in (codex / 'AGENTS.md', codex / 'AGENTS.override.md', scope / 'CLAUDE.md'):
        if not path.is_file():
            continue
        actual = path.resolve()
        before = actual.read_bytes()
        text = before.decode()
        if BEGIN not in text or END not in text:
            continue
        start, end = text.index(BEGIN), text.index(END) + len(END)
        # Strip only our appended separator, leaving all earlier bytes unchanged.
        suffix = text[end:]
        if suffix == '\n':
            prefix = text[:start]
            prefix = prefix[:-1] if prefix.endswith('\n\n') else prefix
            after = prefix.encode()
        else:
            after = (text[:start] + suffix).encode()
        atomic_write(actual, after, actual.stat().st_mode & 0o777)
        changed.append(str(actual))
    for path in (codex / 'hooks.json', claude / 'settings.json'):
        if not path.is_file():
            continue
        obj = json.loads(path.read_bytes())
        removed = False
        for event, groups in list(obj.get('hooks', {}).items()):
            for group in groups:
                old = group.get('hooks', [])
                group['hooks'] = [h for h in old if str(target / 'scripts/handoff.py') not in h.get('command', '')]
                removed = removed or len(old) != len(group['hooks'])
            groups[:] = [g for g in groups if g.get('hooks')]
            if not groups:
                del obj['hooks'][event]
        if removed:
            atomic_write(path, (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode(), path.stat().st_mode & 0o777)
            changed.append(str(path))
    for path in (agents / 'skills/project-handoff', claude / 'skills/project-handoff'):
        if path.is_symlink() and path.resolve() == target:
            path.unlink()
            changed.append(str(path))
    return {'removed_entrypoints': changed, 'preserved': 'Project checkpoints, package, backups, and unrelated settings.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projects-root', type=Path, default=Path('/Volumes/T7/Projects'))
    parser.add_argument('--codex-home', type=Path, default=Path.home() / '.codex')
    parser.add_argument('--claude-home', type=Path, default=Path.home() / '.claude')
    parser.add_argument('--agents-home', type=Path, default=Path.home() / '.agents')
    parser.add_argument('--apply', action='store_true', help='Write the reviewed installation; default is a read-only plan.')
    parser.add_argument('--uninstall', action='store_true', help='Remove only this installation\'s entrypoints; preserve notes.')
    args = parser.parse_args()
    try:
        if args.uninstall:
            if not args.apply:
                raise ValueError('Uninstall requires --apply')
            result = uninstall(args.projects_root, args.codex_home, args.claude_home, args.agents_home)
        else:
            source = Path(__file__).resolve().parent.parent
            target, items = build_plan(source, args.projects_root, args.codex_home, args.claude_home, args.agents_home)
            result = apply_plan(target, items) if args.apply else {
                'target': str(target), 'writes': len(items),
                'paths': [{k: v for k, v in x.items() if k not in ('before', 'after')} for x in items],
                'scope': 'T7 Projects and linked Git worktrees only. Existing project files and unrelated hooks are preserved.',
                'activation': 'Restart sessions; review new Codex hooks in /hooks. No trust bypass.'}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
