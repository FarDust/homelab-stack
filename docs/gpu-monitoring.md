# Optional GPU history integration

The shared Prometheus service supports generic NVIDIA-exporter file discovery.
No device, host, model or project is selected by public configuration.

- `NVIDIA_GPU_TARGETS_FILE`: optional deployment target file, relative to the
  compose file or absolute. Default: the committed empty discovery example.
  Put real private targets/labels in ignored deployment configuration. Explicit
  private `job` labels can preserve series identity during discovery migrations.
- `GRAFANA_GPU_HISTORY_FILE`: optional dashboard artifact. Default: the committed
  generic GPU dashboard example. Deployment-specific dashboards and datasource
  IDs belong in private IaC, not the public parent. The public parent needs no
  credential to clone a private child.

Keep collection read-only. Validate driver compatibility on the actual device
host and preserve existing TLS/authentication boundaries. Route real telemetry
to the existing backend rather than creating a duplicate TSDB. Missing telemetry
stays unknown, not zero GPU utilization; useful work requires independent evidence.

Verify retained age and size-based eviction headroom before claiming a historical
window is covered. New series cannot reconstruct unobserved past usage. Preserve
existing volumes, history, placement and unrelated targets. Validate both public
defaults and actual deployment inputs with Compose and Promtool, then use the
canonical service-scoped cluster-utils deployment workflow.
