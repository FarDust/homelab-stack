# Open PR feed for node-retention

Status: accepted, 2026-11-25. Implementation: `tools/open-prs-feed` (0.1.0). Consumer: `tools/node-retention`
(`adapters/open_prs.py`, `application/floor_step_down.py`), see [node_disk_retention_adr.md](node_disk_retention_adr.md).

## Context

node-retention 0.6.0 steps down ended CI job directories while the root filesystem of the build node is under its
floor. A directory whose name or ledger text carries a PR number (`pr201-3c9b623`, "merge gate for PR #382") is
kept while that PR is open. Open PRs come from a file named by `NODE_RETENTION_OPEN_PRS_FILE`: a JSON array of
positive ints, treated as unknown when missing, older than 2 hours or of any other shape. Unknown keeps every
PR-tied directory. Nothing wrote that file, so every PR-tied directory was kept forever.

The build node has no GitHub API credential: no `gh` login, and its SSH keys are deploy keys of unrelated
repositories. Deploy keys can list `refs/pull/*/head` but not whether a PR is open. Creating a new token is a
credential decision outside this change.

## Decision

- A small uv package, `open-prs-feed`, fetches open PRs through the GitHub CLI and writes two files. Owner scope
  (`OPEN_PRS_FEED_OWNERS`) runs one paginated GraphQL query (`gh api graphql --paginate --slurp`) over every
  non-archived repository the owner owns; repository scope (`OPEN_PRS_FEED_REPOS`) runs
  `gh pr list --state open --json number,headRefOid,headRefName,updatedAt`. Owner scope is the deployed choice:
  job directories on the node come from more repositories than the ones a lane names, and a PR of an uncovered
  repository would look closed. The two files are: the consumer's
  `open-prs.json` (numbers only, unchanged contract) and `open-prs.detail.json` (repo, number, 8-character head SHA,
  branch, update time, generation time).
- It runs on a host that already has an authenticated `gh` and SSH access to the build node, and writes over
  OpenSSH: a temporary file in the target directory, a byte-count check, `chmod 0644`, `mv -f`. Locally it uses
  `mkstemp`, `fsync` and `os.replace`. The schedule is every 15 minutes, well inside the consumer's 2-hour age limit.
- Fail closed. Any repository that fails (missing binary, timeout, nonzero exit, non-JSON, missing or invalid field,
  repeated number, a full `--limit` page, a GraphQL `totalCount` that disagrees with the returned rows, pagination
  that stops early, GraphQL `errors`, an unknown owner, fewer visible repositories than
  `OPEN_PRS_FEED_MIN_OWNER_REPOS`) or an all-empty answer stops the run with exit 1 before anything is
  written. The detail file is written first, so a failed write never replaces the consumer's last good file. If the
  producer stops, the file ages past 2 hours and the consumer goes back to keeping everything. A genuinely empty
  state (zero open PRs) also fails by default and lets the file go stale, the keep-everything side, because the
  consumer reads `[]` as "nothing is open" and would release every PR-tied directory.
- A `gh` login that silently loses private-repo scope (token or SSO restriction) answers with fewer repositories
  and no error, and the hidden repositories' PRs would look closed. The visible-repository floor
  (`OPEN_PRS_FEED_MIN_OWNER_REPOS`, set a little below the owner's current count) turns that into a failure.
- A repository with more than 100 open PRs is re-read through `gh pr list --limit` instead of nested GraphQL
  pagination, because `gh api --paginate` follows a single `pageInfo` per query.
- Archived repositories are left out: they run no CI. PRs the owner opens against other owners' repositories are
  covered only when listed in `OPEN_PRS_FEED_REPOS`.
- Numbers from all repositories form one set. A number open in one repository also protects a same-numbered
  directory of another, which errs toward keeping. With owner scope the low numbers (old repositories with
  long-open dependency PRs) are almost all open, so directories named `pr<small n>` are rarely released; a
  repository-aware consumer would need the repository in the directory name or ledger row, which job dirs lack today.
- Repository names, the target host and the target directory are private settings (`OPEN_PRS_FEED_*` env file
  outside this repository).

## Alternatives

- Run on the build node with its own token: best placement (no producer host to keep alive), but it needs a
  read-only fine-grained token in custody on the node. Prepared for: the same package runs there with
  `OPEN_PRS_FEED_SSH_HOST` unset and the systemd units in `deploy/`.
- A step in each repository's CI workflow: GitHub Actions is billing-blocked for these repositories.
- `git ls-remote refs/pull/*`: shows every PR ever opened, not the open ones.
- Calling the REST API with httpx: the GitHub CLI already owns authentication and pagination on the producer host;
  a second client would duplicate it. Retries are not needed: the next 15-minute run is the retry.
- A richer consumer schema with SHAs: node-retention only matches PR numbers today, and SHA-only directory names
  are not PR-tied there. The detail file keeps the SHA data available without changing the consumer.

## Libraries

| Library | Role | Stars / provider | Licence |
| --- | --- | --- | --- |
| GitHub CLI (`gh`) | API client and auth | GitHub first-party, >40k stars | MIT |
| OpenSSH | remote write | OpenBSD project, system package | BSD |
| pydantic, pydantic-settings | row and settings validation | >20k stars / pydantic team (first-party) | MIT |
| Typer, Rich | CLI and stderr tables | >15k / >50k stars | MIT |

## Consequences

- A merged or closed PR's directories become eligible for step-down on the next node-retention run after the next
  feed run, still subject to the ledger-ended and untouched gates (1 to 3 days).
- The producer host is a dependency. When it is off, the file goes stale and the old behaviour (keep every PR-tied
  directory) returns until it runs again. The Windows task runs as the logged-on user with no stored password, so it
  also pauses while that user is logged off.
- Rollback and uninstall: `systemctl --user disable --now open-prs-feed.timer`, or on Windows
  `Unregister-ScheduledTask -TaskName open-prs-feed -Confirm:$false`; the consumer returns to keeping everything
  after 2 hours.
- Known limitation: numbers merge across repositories, so a `pr2-*` directory stays protected while PR 2 of any
  repository is open (safe side). Repository-aware matching needs the repository in job directory names; follow-up.
- The SSH write uses the build node's existing deploy alias and key. A dedicated key restricted to a forced write
  command would be least privilege; follow-up.

## Verification

- `tools/open-prs-feed/tests/test_feed.py`: consumer contract, merged numbers, mtime refresh, each missing field,
  malformed output (non-JSON, wrong shape, bool, negative, short SHA, naive time, duplicates), API failure in one of
  several repositories, missing binary, timeout, full page, empty snapshot, detail-write failure, SSH sink argv and
  remote failure, settings validation and CLI exit codes. Every failure case asserts the last good file is unchanged.
- The SSH sink's remote script runs through a local POSIX `sh` in two tests (quoted directory, mode, no temp left,
  size mismatch keeps the last good file); they are skipped on Windows and run in CI.
- Live, 2026-11-25: one owner run covered 157 non-archived repositories and 239 open PRs (100 distinct numbers,
  at most 29 PRs in one repository) in 9 s, well inside the 60 s `gh` timeout. The node-retention `OpenPrsFile`
  reads the published numbers; a directory of an open PR stays tied, and directories of merged PRs are released.
