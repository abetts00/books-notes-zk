# Learnings

End-of-session proposals from the `Stop` hook, driven by
`scripts/session_learnings.py`.

## Layout

```
learnings/
├── pending/   ← new proposals land here (git-tracked, uncommitted by default)
└── applied/   ← move a file here after you've merged its changes
```

## Workflow

1. Session ends → hook runs `scripts/session_learnings.py`.
2. The script reads the transcript, loads `SKILL.md`, `CLAUDE.md`, and
   `references/*.md`, and asks Claude to propose minimal diffs.
3. If any durable lessons are found, a markdown file is dropped in
   `pending/` named `<UTC timestamp>-<session prefix>.md`.
4. You review, apply edits manually (or hand them to Claude Code), then move
   the file into `applied/` and commit alongside the doc changes.

## Disabling

Remove the `Stop` hook from `.claude/settings.json` or set the env var
`ANTHROPIC_API_KEY=""` before starting the session — the script exits silently
without an API key.

## Tuning

Environment variables:

| Var | Default | Purpose |
|-----|---------|---------|
| `LEARNINGS_MODEL` | `claude-sonnet-4-6` | Model used to draft the proposal |
| `ANTHROPIC_API_KEY` | — | Required; unset disables the hook |

Edit `PROMPT` in `scripts/session_learnings.py` to change what the reviewer
looks for. The docs it loads are listed in the `DOCS` constant — add new
files there if you want them considered.
