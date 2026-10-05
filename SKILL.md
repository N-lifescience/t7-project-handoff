---
name: project-handoff
description: Checkpoint or resume development under /Volumes/T7/Projects, including linked Git worktrees, using short local session notes. Use for saving progress, handing off, or continuing previous work. Does not apply to unrelated projects.
---

# Project handoff

Apply only to T7 Projects and its linked Git worktrees. Follow [RULES.md](RULES.md).

## Resume

1. Identify the actual working repository or project directory. Use
   `python3 /Volumes/T7/Projects/_workspace-rules/project-handoff/scripts/handoff.py list --root "<directory>"`
   to see recent note titles and statuses. Add `--query "<topic>"` to find an older task.
   Topic queries also search `.handoff/archive/`; `--include-archive` lists it
   explicitly. The default view is kept small by moving completed notes older
   than 30 days to the archive while retaining the 20 newest completed notes.
2. Read the note matching the user's task, normally one note. A completed note is
   history, not an instruction to restart its task. If several active tasks fit,
   ask which one to continue. The user's current instructions take precedence.
3. Check the working tree and the relevant files before acting. Notes describe
   observations; verify commands, file paths, branch/HEAD, deployment state,
   and test results when they matter. Do not replay deployment or external writes
   merely because a note mentions them.
4. Read only the additional source or reference sections needed for the task.
   Existing repository safety and implementation instructions still apply.

## Checkpoint

Use the session-specific path supplied by the hook. If unavailable, choose a
unique `.handoff/<date>-<task>-<random>.md` in the working project; never overwrite
another session's note. `handoff.py init --root "<directory>"` creates the local
note directory and its Git ignore file. Reuse your own note within the session.

Write a current snapshot, preferably 20–60 lines, at most 8,000 UTF-8 bytes and
100 lines. Use the headings below; content may be Korean. Put detailed history
or specifications in the appropriate project document and link to them.

```markdown
# Task: <short task title>
Status: in-progress | done | blocked
Updated: <ISO timestamp with time zone>
Branch: <current branch or non-git>
HEAD: <full current commit SHA or non-git>

## Goal
User's objective and completion condition.
## Done
Changes actually completed; distinguish implementation from deployment.
## Decisions
Decisions and user constraints that cannot be inferred from the source.
## Files
Relevant relative paths and why the next session should open them.
## Checks
Checks actually run and their results; explicitly say what is unverified.
## Next
The next concrete action, or "None — task complete".
## Risks
Known failures, blockers, and assumptions; "None known" if appropriate.
```

Save after a useful milestone and before a substantive final reply, a break,
compaction, or a model handoff. Do not rewrite notes for greetings or routine
questions that add no lasting project information. Preserve important context
before shortening your note. Do not include secrets, student data, transcripts,
large logs, or entire code blocks. Validate with
`handoff.py check "<note-path>" --root "<directory>" --seal` after the final source
change or commit. This adds a file-state fingerprint so later deletions or edits
cannot make an old checkpoint appear current. It checks structure and freshness,
not the truth or completeness of the prose.

Old completed notes are moved, never deleted. Active/blocked notes are retained.
To inspect archival candidates without moving anything, run
`handoff.py archive --root "<directory>"`; add `--apply` to move them.
