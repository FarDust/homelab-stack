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

The host rsyslog schedule candidate is source at `host-config/logrotate/rsyslog.conf`,
governed by the [activation and rollback decision](../../docs/adr/rsyslog_retention_schedule_adr.md).
It is not installed by this CLI. Native regression checks require Linux's installed
`logrotate` and use synthetic logs in debug mode only:

```bash
uv run --python 3.13 --project tools/node-retention pytest -q tools/node-retention/tests/test_logrotate_policy.py
```
