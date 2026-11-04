# ADR: Grafana-managed ingress alert routing

Date: 2026-10-10 16:13 UTC

## Context

The cluster already has Prometheus scrape and blackbox configuration for ingress-control-plane probes. The user requirement is to keep Grafana as the single alert routing layer, with the standalone Prometheus Alertmanager retained only as a cheap safety net for monitoring/Grafana-down scenarios.

Grafana documentation for configuring Alertmanagers states that the built-in Grafana Alertmanager can only handle Grafana-managed alerts. Prometheus documentation supports routing Prometheus alerts to Alertmanager instances, but that does not make Prometheus alerts Grafana-managed.

## Decision

Ingress control-plane notifications are provisioned as Grafana-managed alert rules in `stacks/main/configs/grafana/provisioning/alerting/behavioral_rules.yml`, querying the existing Prometheus datasource `PBFA97CFB590B2093`. Notification policy routing is explicit for `tier=core`, using the existing `grafana-default-broadcast` plus `grafana-routine-n8n` route pattern.

Prometheus alert rules remain useful for local `promtool` validation and for the independent Alertmanager safety net, but Prometheus is not configured to send these alerts to Grafana's built-in Alertmanager.

## Alternatives

1. Configure Prometheus `alerting:` to target Grafana's built-in Alertmanager. Rejected because Grafana's built-in Alertmanager handles only Grafana-managed alerts.
2. Make the standalone Alertmanager the main routing layer. Rejected because it creates a second primary notification policy surface and conflicts with the user's Grafana-routing preference.
3. Keep only Prometheus alert rules. Rejected because Grafana notification policies would not own routing for those alerts.

## Consequences

Grafana must be redeployed after alert provisioning changes so the config files are loaded. Validation must cover both Grafana provisioning YAML and Prometheus rule/target syntax. The standalone Alertmanager remains intentionally narrow and should not become a parallel primary notification pipeline without a new decision.

## Verification

Run YAML parsing, `promtool check rules`, `promtool check config`, `cluster-utils` render/validation for the affected stacks, deploy through `cluster-utils`, then verify Grafana alert rule provisioning and blackbox probe metrics.
