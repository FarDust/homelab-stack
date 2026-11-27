# ADR: Root filesystem free-space alerts for every Swarm node

Date: 2026-11-27

## Context

On 2026-11-27 the root filesystem of frost-fang reached 93 percent used (5.9 GB free of 80 GB) because of unpruned uv caches, stale CI fallback worktrees and an unrotated syslog. Nothing alerted: the only filesystem signals were dashboard panels. This ADR adds the missing alert. It follows `docs/adr/grafana_managed_ingress_alert_routing_adr.md` (Grafana owns routing; rules are provisioned from `stacks/main/configs/grafana/provisioning/alerting/behavioral_rules.yml`; tier `core` goes to Telegram plus the n8n webhook).

## Decision

Add two rules to the group `Host resource alerts` (folder `Behavioral`, 60 s interval), evaluated on `node_filesystem_avail_bytes{job="node-exporter",mountpoint="/"}` for every node-exporter target (tmpfs, overlay, squashfs and ramfs excluded):

| Rule | Condition | For | Labels |
| --- | --- | --- | --- |
| `node_root_fs_low_free_pct` | free below 20 percent of the filesystem size AND below 50 GB AND at least 4 GB | 10 m | `severity=warning`, `tier=core`, `service=host-resources` |
| `node_root_fs_critical_free_bytes` | free below 4 GB (4e9 bytes) | 10 m | `severity=critical`, `tier=core`, `service=host-resources` |

The `nodename` label is joined from `node_uname_info` so messages name the node. `noDataState: OK` (a missing target is covered by `service_down`), `execErrState: Error`.

Why these numbers (measured through Grafana on 2026-11-27): root free was 14 percent (130 GB) on the 930 GB tralmor node, 16 percent (13.5 GB) on frost-fang and 3.4 percent (11 GB) on the gabriel-pc-wsl VHD. A pure 20 percent rule would page permanently for tralmor, where 130 GB is ample, so the warning also requires under 50 GB free. The warning excludes the critical range so one condition never raises both. Both use `tier=core` because the warning exists to be seen before the critical one, and the n8n-only `maintenance` tier is not read in time.

## Alternatives

- Prometheus alert rules with the standalone Alertmanager: rejected by the ingress ADR (a second routing surface).
- `predict_linear` exhaustion alerts: valuable for bursty CI growth, deferred; the fixed thresholds are the requested minimum.
- Pure percentage warning: rejected for tralmor noise (above).

## Consequences

- At creation, frost-fang and gabriel-pc-wsl are in the warning range, so the warning fires: a true positive.
- Alert labels follow the standing schema (`severity`, `tier`, `service`, instance labels `instance`, `nodename`), so the n8n Notification Forwarder rebuild needs no special case.

## Verification

`alerting_manage_rules list` shows both rules after the Grafana redeploy; the expression was queried through Grafana first. A synthetic test temporarily lowers a rule threshold in Grafana (not in the repository) so it fires, confirms delivery to the Telegram contact point, then restores it. Rollback: remove the two rules from `behavioral_rules.yml`, bump `CONFIG_VERSION`, redeploy `grafana`.
