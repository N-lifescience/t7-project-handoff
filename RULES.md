# T7 session continuity

For work under `/Volumes/T7/Projects` or its linked Git worktrees:

- On a fresh session, list `.handoff/*.md` titles and read the note matching the
  current task, normally one. Follow the current user request. Verify the working
  tree and relevant source before continuing. Read more context only as needed.
- After meaningful progress or decisions, update your own short session note
  before the substantive final reply. Also checkpoint at useful milestones and
  before a break or handoff. Skip note writes for casual chat with no new state.
- Use the session-specific note path supplied by the hook, or a unique filename
  in the working project's `.handoff/`. Never overwrite another session's note.
- Include goal, completed work, decisions, relevant files, checks with results,
  next action, and risks. Prefer 20–60 lines; keep each note within 8,000 UTF-8
  bytes and 100 lines. Record the actual branch and full HEAD SHA, or `non-git`.
- Replace your own snapshot instead of appending a diary. Keep essential detail
  in task documents and link to it. Preserve existing `HANDOFF.md`, `PROGRESS.md`,
  and other archives; consult relevant sections when necessary. Repository
  safety and implementation instructions remain in force.
- At session start, the local hook moves completed notes older than 30 days to
  `.handoff/archive/`, retaining the 20 newest completed notes and the current
  session's note. Active/blocked notes remain. No notes are deleted. The default
  listing excludes the archive; a topic query searches it when needed.
- No secrets, student information, transcripts, large logs, or copied source.
  Notes are local working records, not proof of tests, deployment, or approval.
- Use the `project-handoff` skill for checkpoint/resume details; if it is not
  discovered, read `/Volumes/T7/Projects/_workspace-rules/project-handoff/SKILL.md`.
- Optimize by reading relevant context. Do not run keepalive requests, repeated
  compaction, unnecessary summaries, or API calls to maintain a cache. Choose
  model and reasoning effort for the task; change them when the benefit warrants
  it. This workflow does not promise a particular subscription saving.
