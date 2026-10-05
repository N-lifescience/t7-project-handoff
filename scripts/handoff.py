#!/usr/bin/env python3
"""Small local checkpoints for Claude Code and Codex; no API or transcript reads."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

SCOPE = Path('/Volumes/T7/Projects')
SECTIONS = ('Goal', 'Done', 'Decisions', 'Files', 'Checks', 'Next', 'Risks')
IGNORE = {'.git', '.handoff', 'node_modules', '.next', 'dist', 'build',
          '.venv', 'venv', '.cache', '.pnpm-store', '__pycache__',
          'coverage', '.DS_Store'}


def within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=2, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    return result.stdout if result.returncode == 0 else b''


def project(cwd, scope=SCOPE):
    cwd, scope = Path(cwd).resolve(), Path(scope).resolve()
    if not cwd.is_dir():
        return None
    top = git(cwd, 'rev-parse', '--show-toplevel').decode().strip()
    if top:
        root = Path(top).resolve()
        common = git(cwd, 'rev-parse', '--git-common-dir').decode().strip()
        common = (cwd / common).resolve() if common else root / '.git'
        origin = common.parent
        if within(root, scope) or within(origin, scope):
            anchor = root if within(root, scope) else origin
            rel = anchor.relative_to(scope)
            if rel.parts and not rel.parts[0].startswith(('.', '_')):
                return root
        return None
    if within(cwd, scope):
        parts = cwd.relative_to(scope).parts
        if parts and not parts[0].startswith(('.', '_')):
            return scope / parts[0]
    return None


def excluded(relative):
    return any(part in IGNORE for part in Path(relative).parts)


def stamp(path):
    try:
        stat = path.lstat()
        return [stat.st_mtime_ns, stat.st_size, stat.st_mode]
    except FileNotFoundError:
        return None


def snapshot(root):
    """Metadata only: dirty paths + HEAD, or a bounded non-Git directory walk."""
    head = git(root, 'rev-parse', 'HEAD').decode().strip()
    files, limited = {}, False
    deadline = time.monotonic() + 1.5
    if git(root, 'rev-parse', '--is-inside-work-tree').strip() == b'true':
        records = git(root, 'status', '--porcelain=v1', '-z',
                      '--untracked-files=all', '--ignore-submodules=all').split(b'\0')
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            status = record[:2].decode(errors='replace')
            name = os.fsdecode(record[3:])
            if 'R' in status or 'C' in status:
                index += 1  # -z puts the old path in the following record.
            if excluded(name):
                continue
            files[name] = [status, stamp(root / name)]
            if len(files) >= 10000 or time.monotonic() > deadline:
                limited = True
                break
    else:
        for directory, dirs, names in os.walk(root, followlinks=False):
            base = Path(directory)
            dirs[:] = sorted(d for d in dirs if d not in IGNORE
                             and not (base / d).is_symlink())
            if len(base.relative_to(root).parts) > 10:
                dirs[:] = []
                limited = True
                continue
            for name in sorted(names):
                rel = str((base / name).relative_to(root))
                if not excluded(rel):
                    files[rel] = stamp(base / name)
                if len(files) >= 10000 or time.monotonic() > deadline:
                    limited = True
                    break
            if len(files) >= 10000 or time.monotonic() > deadline:
                break
    return {'head': head, 'files': files, 'limited': limited}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def seal(path, root):
    errors = validate(path, root)
    if errors:
        return errors
    text = re.sub(r'\n?<!-- handoff-state: [a-f0-9]+ -->\s*$', '', path.read_text()).rstrip()
    text += '\n\n<!-- handoff-state: ' + fingerprint(snapshot(root)) + ' -->\n'
    if len(text.encode('utf-8')) > 8000 or len(text.splitlines()) > 100:
        return ['checkpoint plus state marker exceeds the size limit']
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return []


def notes(root, limit=8, query='', include_archive=False):
    directory = root / '.handoff'
    if not directory.exists():
        return []
    result = []
    paths = list(directory.glob('*.md'))
    if (query or include_archive) and not (directory / 'archive').is_symlink():
        paths.extend((directory / 'archive').glob('*.md'))
    for path in paths:
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('r', encoding='utf-8', errors='replace') as handle:
            prefix = handle.read(1000)
        title = next((x[2:] for x in prefix.splitlines() if x.startswith('# ')), path.stem)
        status = next((x for x in prefix.splitlines() if x.startswith('Status:')), 'Status: unknown')
        if query and query.casefold() not in (title + ' ' + path.name).casefold():
            continue
        result.append((path.stat().st_mtime_ns,
                       f'{path.relative_to(directory)} | {title[:100]} | {status[:50]}'))
    return [line for _, line in sorted(result, reverse=True)[:limit]]


def archive_completed(root, keep=20, days=30, apply=False, protected=None):
    """Move old completed snapshots out of the default view; never delete notes."""
    directory = root / '.handoff'
    archive = directory / 'archive'
    if not directory.is_dir() or directory.is_symlink() or archive.is_symlink():
        return []
    completed = []
    for path in directory.glob('*.md'):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open(encoding='utf-8', errors='replace') as handle:
            prefix = handle.read(1000)
        if re.search(r'^Status: done\s*$', prefix, re.M):
            completed.append((path.stat().st_mtime_ns, path))
    cutoff = time.time_ns() - max(0, days) * 86400 * 1000000000
    candidates = [(mtime, path) for mtime, path in sorted(completed, reverse=True)[max(0, keep):]
                  if mtime < cutoff and path != protected]
    if not apply or not candidates:
        return [str(path.relative_to(root)) for _, path in candidates]
    lock = directory / '.archive-lock'
    try:
        lock.mkdir()
    except FileExistsError:
        return []  # Another session is archiving; normal work should continue.
    moved = []
    try:
        archive.mkdir(exist_ok=True)
        for mtime, path in candidates:
            if not path.exists() or path.is_symlink() or path.stat().st_mtime_ns != mtime:
                continue
            destination = archive / path.name
            if destination.exists():
                destination = archive / (path.stem + '-' + str(time.time_ns()) + '.md')
            path.rename(destination)
            moved.append(str(destination.relative_to(root)))
    finally:
        lock.rmdir()
    return moved


def validate(path, root=None):
    errors = []
    if root and (root / '.handoff').is_symlink():
        return ['checkpoint directory must not be a symlink']
    if not path.is_file() or path.is_symlink():
        return ['checkpoint is missing or is a symlink']
    if root and not within(path.resolve(), (root / '.handoff').resolve()):
        return ['checkpoint must be inside the working project .handoff directory']
    if path.stat().st_size > 8000:
        return ['checkpoint exceeds 8,000 UTF-8 bytes']
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return ['checkpoint is not UTF-8']
    if len(text.splitlines()) > 100:
        errors.append('checkpoint exceeds 100 lines')
    if not re.search(r'^# Task: \S.*$', text, re.M):
        errors.append('missing task title')
    if not re.search(r'^Status: (in-progress|done|blocked)\s*$', text, re.M):
        errors.append('invalid status')
    for label in ('Updated', 'Branch', 'HEAD'):
        if not re.search(r'^' + label + r': \S.+$', text, re.M):
            errors.append('missing ' + label)
    for section in SECTIONS:
        match = re.search(r'^## ' + section + r'\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
        if not match or not match.group(1).strip():
            errors.append('missing or empty ' + section)
        elif match.group(1).strip() in ('...', '- ...', 'TODO', '- TODO'):
            errors.append('unfinished ' + section)
    if root:
        head = git(root, 'rev-parse', 'HEAD').decode().strip()
        if head and not re.search(r'^HEAD: ' + re.escape(head) + r'\s*$', text, re.M):
            errors.append('HEAD does not match the working repository')
    return errors


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def hook(payload, backend, scope=SCOPE, runtime=None):
    root = project(payload.get('cwd', os.getcwd()), scope)
    session = payload.get('session_id')
    if root is None or not session:
        return None
    identifier = hashlib.sha256((str(root) + '\0' + backend + '\0' + session).encode()).hexdigest()[:16]
    note = root / '.handoff' / (backend + '-' + identifier + '.md')
    runtime = runtime or Path(tempfile.gettempdir()) / ('t7-project-handoff-' + str(os.getuid()))
    state_path = runtime / (identifier + '.json')
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    event = payload.get('hook_event_name')
    if event in ('SessionStart', 'UserPromptSubmit'):
        first = not state
        # Compaction can happen during a turn; keep the original baseline then.
        if event == 'UserPromptSubmit' or not state:
            state = {'started': time.time_ns(), 'baseline': snapshot(root), 'reminded': False}
            atomic_json(state_path, state)
        if event == 'SessionStart' or first:
            archive_completed(root, apply=True, protected=note)
            recent = notes(root, limit=6)
            context = (f'T7 handoff: working root {root}. Your checkpoint: {note}. '
                       'After meaningful progress, save a short current snapshot before your final reply. '
                       'Read project-handoff/RULES.md if needed. Resume only the note matching the current user task; '
                       'verify source and working tree. Keep existing repository instructions.\n'
                       + ('Recent note titles (read only the relevant note):\n' + '\n'.join(recent)
                          if recent else 'No short checkpoints yet; use relevant existing project records as needed.'))
            return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': context}}
        return None
    if event != 'Stop' or not state:
        return None
    current = snapshot(root)
    if current == state['baseline']:
        return None
    errors = validate(note, root)
    if note.is_file() and not note.is_symlink() and note.stat().st_size <= 8000:
        match = re.search(r'<!-- handoff-state: ([a-f0-9]{64}) -->', note.read_text(errors='replace'))
        if not match or match.group(1) != fingerprint(current):
            errors.append('checkpoint has not been sealed against the current project state')
    if note.exists() and note.stat().st_mtime_ns < state['started']:
        errors.append('checkpoint predates this user turn')
    # Detect edits after a checkpoint, including changes to already-dirty files.
    changed = [name for name, value in current['files'].items()
               if value != state['baseline']['files'].get(name)]
    for name in changed:
        meta = stamp(root / name)
        if note.exists() and meta and meta[0] > note.stat().st_mtime_ns:
            errors.append('project files changed after the checkpoint')
            break
    if not errors:
        return None
    if payload.get('stop_hook_active') or state.get('reminded'):
        return {'systemMessage': 'T7 checkpoint is still incomplete; save it before leaving. ' + '; '.join(errors[:2])}
    state['reminded'] = True
    atomic_json(state_path, state)
    return {'decision': 'block', 'reason':
            f'Save or refresh only your checkpoint at {note}, then finish. '
            f'Use {Path(__file__).resolve().parent.parent / "SKILL.md"} for the format '
            '(Goal, Done, Decisions, Files, Checks, Next, Risks; status, timestamp, branch and full HEAD). '
            'Record observed results, including unverified work. Keep it under 8,000 UTF-8 bytes / 100 lines. '
            'Create .handoff/.gitignore containing * if missing. Do not redo the task or launch another agent. '
            f'Finally run python3 "{Path(__file__).resolve()}" check "{note}" --root "{root}" --seal. '
            'Reason: ' + '; '.join(dict.fromkeys(errors))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('hook')
    p.add_argument('--backend', choices=('codex', 'claude'), required=True)
    p.add_argument('--scope', type=Path, default=SCOPE)
    for name in ('list', 'init', 'check', 'archive'):
        p = sub.add_parser(name)
        p.add_argument('--root', type=Path, default=Path.cwd())
        if name == 'list':
            p.add_argument('--query', default='')
            p.add_argument('--limit', type=int, default=8)
            p.add_argument('--include-archive', action='store_true')
        elif name == 'check':
            p.add_argument('path', type=Path)
            p.add_argument('--seal', action='store_true', help='Record the current file-state fingerprint after validation.')
        elif name == 'archive':
            p.add_argument('--keep', type=int, default=20)
            p.add_argument('--days', type=int, default=30)
            p.add_argument('--apply', action='store_true', help='Move candidates into .handoff/archive; default is a preview.')
    args = parser.parse_args()
    if args.command == 'hook':
        try:
            output = hook(json.load(sys.stdin), args.backend, args.scope)
            if output:
                print(json.dumps(output, ensure_ascii=False))
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            # A checkpoint mechanism must not trap a session on an unavailable disk.
            print(json.dumps({'systemMessage': 'T7 handoff hook could not check progress: ' + type(error).__name__}))
        return 0
    root = args.root.resolve()
    if args.command == 'list':
        print('\n'.join(notes(root, max(1, min(args.limit, 50)), args.query, args.include_archive)) or 'No matching short checkpoints.')
    elif args.command == 'archive':
        result = archive_completed(root, args.keep, args.days, args.apply)
        print('\n'.join(result) or 'No old completed checkpoints to archive.')
    elif args.command == 'init':
        directory = root / '.handoff'
        if directory.is_symlink():
            raise ValueError('checkpoint directory must not be a symlink')
        directory.mkdir(parents=True, exist_ok=True)
        ignore = directory / '.gitignore'
        if not ignore.exists():
            with ignore.open('x') as handle:
                handle.write('*\n')
        print(directory)
    else:
        errors = seal(args.path.resolve(), root) if args.seal else validate(args.path.resolve(), root)
        print('\n'.join(errors) if errors else 'Checkpoint structure valid; factual accuracy still needs review.')
        return 1 if errors else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
