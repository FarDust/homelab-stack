---
name: commit-gpg-tmux
description: Runs GPG-signed git commits inside a tmux session so the user can attach and enter their passphrase. Use when committing in a no-TTY environment, when GPG fails with "signing failed: No such file or directory" or "not a tty", or when the user asks to commit with GPG, use tmux for signing, or send-keys.
---

# Commit GPG Tmux

Runs the commit in a tmux session so the user gets a real TTY for the GPG passphrase. The agent sends the commit via `tmux send-keys`; the user attaches, enters the passphrase, and detaches.

## Quick Start

1. Ensure pre-commit passes on staged files (if the repo uses it).
2. Create or reuse a tmux session; send `export GPG_TTY=$(tty)` then `git commit -m "..."` with `tmux send-keys`.
3. Tell the user to run `tmux attach -t <session>`, enter passphrase, then `Ctrl-b d`.
4. Verify with `tmux capture-pane -pt <session>` and/or `git log -1`.

## When to Use

- User wants to commit with GPG signing and the current shell has no TTY (e.g. agent, CI).
- `git commit` fails with `gpg: signing failed: No such file or directory` or `not a tty`.
- User says "commit with GPG", "use tmux for signing", or "send-keys" for the commit.

## Instructions

### Prerequisites

If the repo uses pre-commit: run `pre-commit run` on staged files and fix any failures before sending the commit to tmux. Avoid mixed staged/unstaged changes on the same files so pre-commit stash restore does not conflict.

### Workflow

Task progress:

- [ ] Pre-commit passes on staged files (if applicable).
- [ ] Tmux session exists or is created; send-keys runs `GPG_TTY` and `git commit`.
- [ ] User attaches, enters passphrase, detaches.
- [ ] Agent verifies with capture-pane and/or `git log -1`.

**Create session** (if needed):

Check for existing session: `tmux list-sessions`. If `compose-gpg` (or your session name) is listed, skip creation and send keys to it.

```bash
tmux new-session -d -s compose-gpg 'cd /path/to/repo && exec $SHELL'
```

Use a stable session name (e.g. `compose-gpg`).

**Send commit:** set `GPG_TTY` then run `git commit` in the same pane. `C-m` is Enter.

```bash
tmux send-keys -t compose-gpg 'export GPG_TTY=$(tty)' C-m \
  'git commit -m "type(scope): short description"' C-m
```

With a body:

```bash
tmux send-keys -t compose-gpg 'export GPG_TTY=$(tty)' C-m \
  'git commit -m "type(scope): short description" -m "Optional body."' C-m
```

**User:** `tmux attach -t compose-gpg` → enter passphrase → `Ctrl-b d`.

**Verify:**

```bash
tmux capture-pane -pt compose-gpg
git log -1 --oneline
git show --name-only -1 --oneline
```

Use `tmux capture-pane` to read the pane (errors or success) without the user pasting.

## Examples

**Example 1: Single commit with conventional message**

Repo at `/path/to/repo`; staged: `.gitignore`, `AGENTS.md`, `README.md`, `.python-version`, `pyproject.toml`, `uv.lock`; `.vscode/settings.json` deleted.

```bash
tmux new-session -d -s compose-gpg 'cd /path/to/repo && exec $SHELL'
tmux send-keys -t compose-gpg 'export GPG_TTY=$(tty)' C-m \
  'git commit -m "chore(root): add python tooling and commit conventions" -m "Track python version and tooling (pyproject/uv.lock), tighten .gitignore, document Conventional Commits in AGENTS.md, remove obsolete VS Code settings."' C-m
```

User: `tmux attach -t compose-gpg` → passphrase → `Ctrl-b d`. Agent: `git log -1 --oneline`.

**Example 2: Read pane after commit (success or failure)**

To see why the commit failed or to confirm the user approved:

```bash
tmux capture-pane -pt compose-gpg
```

## Summary

| Step | Who  | Action |
|------|------|--------|
| 1 | Agent | Pre-commit passes; create session if needed: `tmux new-session -d -s <name> 'cd <repo> && exec $SHELL'` |
| 2 | Agent | `tmux send-keys -t <name> 'export GPG_TTY=$(tty)' C-m 'git commit -m "..."' C-m` |
| 3 | User  | `tmux attach -t <name>`, enter passphrase, `Ctrl-b d` |
| 4 | Agent | `tmux capture-pane -pt <name>` and/or `git log -1` |

## Additional Resources

- Session already exists, multiple commits, session naming, skipping GPG: see [reference.md](reference.md).
