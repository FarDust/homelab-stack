# Commit GPG Tmux — Reference

## Session already exists

If `tmux list-sessions` shows the session (e.g. `compose-gpg`), do not create a new one. Send keys directly:

```bash
tmux send-keys -t compose-gpg 'export GPG_TTY=$(tty)' C-m 'git commit -m "..."' C-m
```

Creating a second session with the same name fails.

## Multiple commits in sequence

Run one commit and wait for the user to attach and sign. After they detach, verify with `git log -1` and `tmux capture-pane`. For the next commit, send keys again to the same session; the pane already has `GPG_TTY` set for that shell, but setting it again each time is harmless and ensures a clean state.

## Session name

Use a stable name (e.g. `compose-gpg`, `commit-gpg`) so the user always runs `tmux attach -t <name>`. Document the name in the skill or in project docs (e.g. AGENTS.md) if the repo standardizes it.

## Skipping GPG

Do not use `git commit --no-gpg-sign` unless the user explicitly asks to skip signing for a one-off. The skill exists to support signing, not to bypass it.
