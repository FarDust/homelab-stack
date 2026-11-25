# open-prs-feed

Writes the list of open pull requests that `tools/node-retention` reads (`NODE_RETENTION_OPEN_PRS_FILE`), so a CI
job directory tied to a PR number stays protected while that PR is open and becomes eligible once it is merged or
closed. Decision record: [docs/adr/open_prs_feed_adr.md](../../docs/adr/open_prs_feed_adr.md).

```bash
uv run --project tools/open-prs-feed open-prs-feed show --env-file <env>      # detail JSON on stdout, writes nothing
uv run --project tools/open-prs-feed open-prs-feed publish --env-file <env>   # writes both files, prints the numbers
```

## Files

- `open-prs.json` (consumer contract): a JSON array of positive PR numbers, for example `[198, 201, 405]`.
  node-retention treats a missing file, a file older than `NODE_RETENTION_OPEN_PRS_MAX_AGE_HOURS` (2 h) or any
  other shape as unknown and then keeps every PR-tied directory.
- `open-prs.detail.json`: `schema_version`, `generated_at`, `owners`, `repos` and one row per PR with `repo`,
  `number`, `head_sha8`, `branch` and `updated_at`. It is written first and is informational: after a failed
  second write it can be one generation newer than `open-prs.json`.

Numbers from several repositories are merged into one set, so a number open in any repository protects matching
directories of all of them (the conservative direction).

## Failure rules

Every configured owner and repository must answer. In owner scope a repository with more than 100 open PRs is
re-read through `gh pr list --limit`; a `totalCount` that disagrees with the rows otherwise, pagination that stops
early, or fewer visible repositories than `OPEN_PRS_FEED_MIN_OWNER_REPOS` (a login that lost private-repo scope)
counts as truncated. A missing binary, timeout, nonzero exit, non-JSON output, a row with a missing or invalid field, a repeated number, a full page (`--limit` reached) or an all-empty answer (unless
`OPEN_PRS_FEED_ALLOW_EMPTY=true`) stops the run with exit 1 before anything is written. The detail file is written
before the numbers file, each through a temporary file in the target directory, a size check and a rename, so the
consumer always sees the last complete list.

## Settings (`OPEN_PRS_FEED_*`)

See `deploy/open-prs-feed.env.example`. Required: `OUTPUT_DIR` and at least one of `OWNERS` (comma-separated GitHub
logins; every non-archived repository they own, through one paginated GraphQL query each) and `REPOS` (comma-separated
`owner/name`, through `gh pr list`). Prefer `OWNERS`: a directory tied to a PR of a repository the feed does not
cover would look closed and could be released while its PR is still open. Set `MIN_OWNER_REPOS` a little below the
owner's current non-archived repository count. With `SSH_HOST` set, `OUTPUT_DIR` is an absolute path on that host and the files are written over OpenSSH.

## Deploy

The feed runs where an authenticated `gh` exists; see the ADR for where that is and why. Linux: copy the project,
`uv sync --frozen`, install `deploy/open-prs-feed.service` and `.timer` as user units, `systemctl --user enable --now
open-prs-feed.timer`. Windows: `deploy/register-windows-task.ps1` registers a hidden 15-minute task that runs as the current user while
that user is logged on, with no stored password; the SSH alias must authenticate unattended (key or agent). Uninstall:
`systemctl --user disable --now open-prs-feed.timer`, or on Windows
`Unregister-ScheduledTask -TaskName open-prs-feed -Confirm:$false`. node-retention then sees a stale file after 2 h and
keeps every PR-tied directory again. Tested with GitHub CLI 2.96 (`gh api graphql --paginate --slurp`).

Tests: `uv run --python 3.13 --project tools/open-prs-feed pytest`.
