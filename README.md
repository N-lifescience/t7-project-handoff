# T7 Project Handoff

A small local checkpoint skill and lifecycle harness for Claude Code and Codex.
It targets projects under `/Volumes/T7/Projects` and their linked Git worktrees.

Each session writes a short current snapshot in the working project's
`.handoff/` directory. Saving replaces that session's snapshot instead of
appending a diary. Notes are limited to 8,000 UTF-8 bytes and 100 lines.
At session start, the harness shows up to six recent note titles so the agent
can read the relevant note before loading more context.

Completed notes older than 30 days are moved into `.handoff/archive/`, retaining
the 20 newest completed notes and the current session's note. Active and blocked
notes stay available. Nothing is deleted; topic searches include the archive.

The hook scripts use Python's standard library. They inspect local file metadata
and Git state; they do not call a model, scan chat transcripts, or send cache
keepalive requests. If source changes have no valid current checkpoint, the
Stop hook requests one correction per user turn. Writing that correction still
uses the agent's normal tokens. Structural checks cannot prove the note's facts.

## Installation

Requirements: macOS, Python 3.9 or later, Git, a mounted T7 with a `Projects`
directory, and Claude Code or a Codex version supporting lifecycle hooks.

```sh
git clone https://github.com/N-lifescience/t7-project-handoff.git
cd t7-project-handoff
python3 scripts/install.py          # preview paths and changes
python3 scripts/install.py --apply  # install
```

The installer copies the package into
`/Volumes/T7/Projects/_workspace-rules/project-handoff`, adds a T7-only instruction
to Codex's user guidance and the Projects `CLAUDE.md`, merges three hooks per
provider, and links the shared skill into the user skill directories.
Existing instruction text, unrelated settings/hooks, and instruction symlinks
are preserved. Configuration backups are local, Git-ignored, and owner-readable.

Restart sessions after installation. In Codex, open `/hooks` to review and trust
the three new handlers. The installer does not bypass hook trust. In Claude Code,
accept the normal workspace/settings review if your version requests it.

Invoke `/project-handoff` in Claude Code or `$project-handoff` in Codex. Ordinary
ChatGPT web conversations cannot use these local hooks directly.

See [the Korean usage guide](사용안내.md), [workflow instructions](SKILL.md), and
[short working rules](RULES.md).

## Local commands

```sh
python3 scripts/handoff.py list --root /path/to/project
python3 scripts/handoff.py list --root /path/to/project --query "task topic"
python3 scripts/handoff.py init --root /path/to/project
python3 scripts/handoff.py check /path/to/project/.handoff/session.md --root /path/to/project --seal
python3 scripts/handoff.py archive --root /path/to/project          # preview
python3 scripts/handoff.py archive --root /path/to/project --apply  # move old completed notes
```

To remove this package's instruction blocks, hooks, and skill links while keeping
notes and backups:

```sh
python3 scripts/install.py --uninstall --apply
```

## Verification and limits

```sh
python3 -m unittest discover -s tests -v
```

The tests cover scope, Git worktrees, note freshness, correction limits, archiving,
configuration preservation, install idempotence, and rollback on conflicting edits.
File scans are bounded; generated directories are excluded. Interruptions,
unavailable disks, API errors, and disabled/untrusted hooks can skip the final
check, so agents should also checkpoint at useful milestones. This package
does not promise a particular token or subscription saving.

Public source excludes local installation receipts, configuration backups,
personal settings, session checkpoints, and other T7 projects.
