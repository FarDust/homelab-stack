# Changelog

## 0.1.0

- First release: `publish` and `show` commands, owner scope (one paginated GraphQL query over every non-archived
  repository, a visible-repository floor, `gh pr list` fallback above 100 open PRs) and repository scope
  (`gh pr list`), strict row validation, refusal of partial,
  truncated and empty snapshots, atomic local and SSH sinks (temp file, size check, rename), detail file written
  before the consumer file, systemd user timer and a Windows Task Scheduler launcher. See
  `docs/adr/open_prs_feed_adr.md`.
