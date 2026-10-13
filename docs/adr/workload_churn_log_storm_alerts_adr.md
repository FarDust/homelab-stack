# ADR: Grafana-managed alerts for task churn, log storms and Loki archives

Date: 2026-10-13 07:10 UTC

## Context

On 2026-10-12 the Infinity service restarted 11 times and wrote about 900,000 log lines in 3 hours (about 83 lines/s) before the frost-fang recovery cascade, and nobody was told. The plan "Crash-loop sentinel and log durability" orders the work as: readable and durable logs, then detection from existing data, then an optional sentinel service. This ADR covers the second step. It follows `docs/adr/grafana_managed_ingress_alert_routing_adr.md`: Grafana owns alert routing, rules are provisioned from `stacks/main/configs/grafana/provisioning/alerting/behavioral_rules.yml`, and tiers route through `notification_policies.yml` (`core` and `security` and `anomaly` to Telegram plus the n8n webhook, everything else to the n8n webhook).

## Decision

Add the rule group `Workload and log durability alerts` (folder `Behavioral`, 60 s interval) with six rules:

| Rule | Signal | Threshold | For | Tier |
| --- | --- | --- | --- | --- |
| `swarm_task_churn` | per service, distinct Swarm task ids per node seen in 30 minutes (cAdvisor `container_start_time_seconds`) | at least 5 | 5 m | maintenance |
| `swarm_task_churn_severe` | same | at least 10 | 5 m | core |
| `loki_log_rate_high` | `sum by (service_name) (rate({service_name=~".+", service_name!~"main-storage_postgres"}[5m]))` | above 50 lines/s | 10 m | maintenance |
| `loki_log_rate_postgres_high` | same for `main-storage_postgres` | above 250 lines/s | 10 m | maintenance |
| `loki_backup_stale` | `time() - loki_backup_last_success_timestamp_seconds` | above 129600 s (36 h) | 15 m | maintenance |
| `pg_role_connections_near_limit` | `pg_role_activity_connections / on(rolname) pg_roles_connection_limit` | above 0.75 | 5 m | maintenance |

Why these numbers (measured on 2026-10-13 through Grafana):

- Task churn counts distinct `container_label_com_docker_swarm_task_id` per `(service, node)` in 30 minutes, so a stable service is 1 and global-mode services do not add up across nodes. Over 48 hours most services peak at 1 or 2; incident services reached 10 to 69. The Infinity proxy (cAdvisor series for the removed service) peaked at 5 in 30 minutes, so 5 is the lowest threshold that would have caught it. The severe rule at 10 pages Telegram.
- Log rate: every service except Postgres stayed below 5 lines/s in the last 6 hours (highest litellm burst 4.4). A global limit of 50 is 10 times the normal maximum and below the 83 lines/s incident. Postgres has been at about 133 lines/s since at least 2026-10-12 12:00 UTC because of a connection-error storm; it is excluded from the global rule and has its own limit of 250 that fires on a doubling.
- The archive rule allows three missed 12 hour runs.
- The Postgres connection rule was requested by the Postgres lane (verified ratios 0 to 0.33 when created).

## Alternatives

- Loki ruler (the `ruler` block exists and sends to the standalone Alertmanager): rejected; the ingress ADR keeps Grafana as the single routing layer.
- A custom sentinel for detection: deferred to step 3; detection from existing metrics needs no new code.
- Prometheus-side alerts: rejected for the same routing reason.

## Consequences

- `hobby-gaming_wings` is a real flapper (5 tasks in 30 minutes at deployment time) and will raise the maintenance warning to the n8n webhook. That is a true positive, not noise from the threshold.
- Log-rate rules query Loki, which returned intermittent 500 and 502 for long-range queries during I/O pressure; the rules use a 10 minute instant window, `execErrState: Error` so a failing evaluation is visible, and `noDataState: OK`.
- Rule labels `service` use fixed values (`swarm-health`, `log-volume`, `loki-backup`, `postgres-connections`); the offending service is in the alert instance labels (`container_label_com_docker_swarm_service_name`, `service_name`, `rolname`) and annotations. `task_id` is never used as an alert label.
- Alerts only observe. The scale-down action remains the later sentinel step.

## Verification

Each expression was queried through Grafana first. After the Grafana redeploy, `alerting_manage_rules list` shows the six rules healthy; state is `normal` except genuine true positives, which are listed in the dated report. Rollback: remove the group from `behavioral_rules.yml`, bump `CONFIG_VERSION`, redeploy `grafana`.
