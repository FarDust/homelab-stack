# node-retention

Standing disk retention policy for a CI/build worker node. Decision record:
[docs/adr/node_disk_retention_adr.md](../../docs/adr/node_disk_retention_adr.md).

```bash
uv run --project tools/node-retention node-retention plan          # dry run, Rich table on stderr
uv run --project tools/node-retention node-retention plan --json   # manifest-shaped plan on stdout
uv run --project tools/node-retention node-retention apply         # manifest first, then delete
uv run --project tools/node-retention node-retention guard         # metrics; applies only under the floor
uv run --project tools/node-retention node-retention verify-images # exit 1 when a protected image is missing or drifted
```

Configuration comes from `NODE_RETENTION_*` variables (see `deploy/node-retention.env.example`). Two user
timers run it: `node-retention-guard` every 10 minutes and `node-retention-apply` every 6 hours.

Protected images: `NODE_RETENTION_PROTECTED_IMAGE_REFS` is a JSON object of image reference to expected image id
(empty by default; the node's private settings file supplies the real value, nothing node-specific is committed).
Every image prune is refused, and the command exits 1, when a reference is missing or resolves to another id. Any
other script that prunes images on the node must call `verify-images` first and must never pass `-a` or `--all`.

Layout: `domain` (types, ports, rules; no I/O), `application` (planner, applier, metrics), `adapters` (local
filesystem, `/proc`, Docker CLI, JSONL ledger, textfile publisher), `cli` (composition root).

Run the tests with `uv run --project tools/node-retention pytest`.

## Read-only job reporting

Version 0.4.0 adds a separate `node-retention-report` console command. It reports
stale owner trees and containers through the configured existing ledger publisher;
it never invokes the deletion policy. Required `NODE_RETENTION_REPORT_*` fields
provide job identity, original admission epoch/duration, ledger/jobs paths and
publisher executable. The report worker receives at most four seconds, plus a
one-second native termination grace, inside the original job's remaining budget. Partial and unknown coverage return exit 2 with a typed
JSON outcome; cancellation returns the signal-derived nonzero exit.

See the [reporting decision](../../docs/adr/ci_job_report_budget_adr.md) and
[canonical profile/adoption guide](../../host-config/ci-job-reporting/README.md).
Deployment bindings remain private; the committed profile is synthetic. Existing
retention timers and rsyslog activation are unaffected.

The host rsyslog schedule candidate is source at `host-config/logrotate/rsyslog.conf`,
governed by the [activation and rollback decision](../../docs/adr/rsyslog_retention_schedule_adr.md).
It is not installed by this CLI. Native regression checks require Linux's installed
`logrotate` and use synthetic logs in debug mode only:

```bash
uv run --python 3.13 --project tools/node-retention pytest -q tools/node-retention/tests/test_logrotate_policy.py
```
