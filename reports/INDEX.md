# Reports Index

This index tracks all reports in the repository root `reports/` directory.

## Active Reports

| Report | Date | Status | Priority | Description |
|--------|------|--------|----------|-------------|
| [2026-03-03-tra-217-openhands-k3s-research-gate.md](2026-03-03-tra-217-openhands-k3s-research-gate.md) | 2026-03-03 | ✅ COMPLETED | 🔴 HIGH | TRA-217 research gate: upstream product/runtime review shows OSS OpenHands on K3s is not yet justified as a Keycloak + shared-Postgres cluster app, with approval pivots defined for single-user OSS vs licensed Cloud/Enterprise paths |
| [2026-02-26-tra-166-k3s-template-research-gate-baseline.md](2026-02-26-tra-166-k3s-template-research-gate-baseline.md) | 2026-02-26 | ✅ COMPLETED | 🔴 HIGH | TRA-166 research gate snapshot with repo baseline, primary-source K3s/Helm/Gateway/cert-manager references, and promotion criteria checklist for TRA-119 children |
| [2026-02-26-tra-191-traefik-gateway-baseline-clean-ownership.md](2026-02-26-tra-191-traefik-gateway-baseline-clean-ownership.md) | 2026-02-26 | ✅ COMPLETED | 🔴 HIGH | TRA-191 completion snapshot: clean Helm ownership for Traefik Gateway API baseline, template-managed smoke route, and live end-to-end validation |
| [summary/README.md](summary/README.md) | 2026-02-25 | ✅ COMPLETED | 🟡 MEDIUM | 4-year platform summary pack with chronology, architecture, reliability, storage lifecycle, observability/governance, unresolved-risk snapshot, and git-history provenance/confidence appendix |
| [2026-02-25-tra-114-candidate-3-rejection-observability-consolidation.md](2026-02-25-tra-114-candidate-3-rejection-observability-consolidation.md) | 2026-02-25 | ✅ COMPLETED | 🟡 MEDIUM | Decision snapshot for TRA-114 candidate #3 rejection: keep observability intentionally ad-hoc and best-fit per task; no consolidation parent task created |
| [2026-02-25-linear-parent-issues-to-reports-map.md](2026-02-25-linear-parent-issues-to-reports-map.md) | 2026-02-25 | ✅ COMPLETED | 🟡 MEDIUM | Week snapshot mapping top-level Linear parent issues (`2026-02-23` to `2026-02-25`) to evidence files under `reports/` |
| [2026-02-24-tra-87-longhorn-reboot-proof-validation-progress.md](2026-02-24-tra-87-longhorn-reboot-proof-validation-progress.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-87 closed with explicit risk acceptance: strict controlled reboot proof completed on `gabriel-pc`, and stable-node reboot checks (`frost-fang`, `fardustdev`) deferred to planned maintenance windows |
| [2026-02-24-tra-90-nodegraph-ux-ui-provisioned-rollout.md](grafana-dashboard/analysis/2026-02-24-tra-90-nodegraph-ux-ui-provisioned-rollout.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-90 UX/UI rollout snapshot: provisioned `gamrcvc` dashboard with summary stats, improved node graph semantics, degraded-link table, self-loop suppression, and live deployment/validation evidence |
| [2026-02-24-inotify-1024-all-hosts-maintenance-rollout.md](2026-02-24-inotify-1024-all-hosts-maintenance-rollout.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | Managed rollout of `fs.inotify.max_user_instances=1024` to all active Swarm hosts with persistent `/etc/sysctl.d` reconciliation via `main-maintenance_inotify-sysctl-reconciler` |
| [2026-02-24-tra-88-inotify-pressure-rca.md](2026-02-24-tra-88-inotify-pressure-rca.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-88 RCA snapshot: frost-fang NVIDIA plugin failure is driven by structural inotify instance saturation from mixed k3s + moby + host daemon load, not a single leaking process |
| [2026-02-24-tra-16-c-managed-nvidia-plugin-rollout.md](2026-02-24-tra-16-c-managed-nvidia-plugin-rollout.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-36 rollout snapshot: added managed template+CLI workflow for NVIDIA plugin, resolved runtimeClass/mount mismatch, and restored `2/2` readiness with host inotify-limit blocker identified and tracked as follow-up |
| [2026-02-24-tra-16-b-gpu-runtime-prerequisite-validation.md](2026-02-24-tra-16-b-gpu-runtime-prerequisite-validation.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-35 validation snapshot: NVIDIA runtime is configured but device-plugin startup fails on both GPU nodes due read-only hook mutation path, with additional missing `libcudadebugger.so.1` on `gabriel-pc` |
| [2026-02-24-tra-18-b-data-safe-remediation-runbook.md](2026-02-24-tra-18-b-data-safe-remediation-runbook.md) | 2026-02-24 | ✅ COMPLETED | 🟡 MEDIUM | TRA-47 remediation design snapshot: controlled backup-and-archive runbook with explicit go/no-go gates, reversible rollback, and no blind path deletion |
| [2026-02-24-tra-18-a-comfy-gpu-mountpoint-forensic-baseline.md](2026-02-24-tra-18-a-comfy-gpu-mountpoint-forensic-baseline.md) | 2026-02-24 | ✅ COMPLETED | 🟡 MEDIUM | TRA-46 forensic snapshot: `vision-generation_comfy-gpu` fails on `Gabriel-PC` because rclone plugin propagated mountpoint `vision-generation_comfyui_config` is non-empty while the volume object is missing |
| [2026-02-24-tra-16-a-gpu-plugin-failure-baseline.md](2026-02-24-tra-16-a-gpu-plugin-failure-baseline.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-34 baseline snapshot for NVIDIA plugin: intended GPU-node targeting is correct but both target pods are unhealthy (`CrashLoopBackOff` on frost-fang, `RunContainerError` prestart hook mount failure on gabriel-pc) |
| [2026-02-24-tra-17-d-three-sync-runs-validation.md](2026-02-24-tra-17-d-three-sync-runs-validation.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-33 validation snapshot: three consecutive manual sync runs succeeded and all marker objects were verified under `k8s-hot/k8s/` with no DNS error signature |
| [2026-02-24-tra-17-c-coredns-dns-fix-implementation.md](2026-02-24-tra-17-c-coredns-dns-fix-implementation.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-32 implementation snapshot: added template-safe CoreDNS upstream workflow in `cluster-utils`, applied forward change to Tailscale DNS, and validated sync job recovery |
| [2026-02-24-tra-17-b-dns-mitigation-decision.md](2026-02-24-tra-17-b-dns-mitigation-decision.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-31 decision snapshot: selected CoreDNS explicit Tailscale DNS upstream (`100.100.100.100`) with rollback criteria and temporary node-selector guardrail retention |
| [2026-02-24-tra-17-a-dns-baseline-cephfs-minio-sync.md](2026-02-24-tra-17-a-dns-baseline-cephfs-minio-sync.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-30 DNS baseline for CephFS->MinIO sync: reproducible `no such host` in pod DNS path via kube-dns, with host-path differential proof and CoreDNS runtime/context capture |
| [2026-02-24-tra-15-permanent-mount-propagation-persistence-rollout.md](2026-02-24-tra-15-permanent-mount-propagation-persistence-rollout.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-15 persistence rollout: added commit-safe systemd template, enabled mount-propagation unit on Longhorn data nodes, and validated `enabled/active` plus `shared` propagation on `/`, `/var/lib/kubelet`, and `/var/lib/longhorn` |
| [2026-02-24-tra-15-pvc-smoke-and-rollback-validation.md](2026-02-24-tra-15-pvc-smoke-and-rollback-validation.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-15-D validation: Longhorn PVC write/read/delete succeeded after runtime instance-manager recovery, with cleanup proof and no chart divergence |
| [2026-02-24-tra-15-longhorn-remediation-and-recovery.md](2026-02-24-tra-15-longhorn-remediation-and-recovery.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-15-C execution snapshot: host mount-propagation remediation on `gabriel-pc` and recovery of `longhorn-manager` to `2/2` with node `READY=True` |
| [2026-02-24-tra-15-mount-propagation-normalization-plan.md](2026-02-24-tra-15-mount-propagation-normalization-plan.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | TRA-15-B node-level remediation and rollback plan for mount-propagation normalization with zero Longhorn chart divergence |
| [2026-02-24-tra-15-longhorn-mount-propagation-baseline.md](2026-02-24-tra-15-longhorn-mount-propagation-baseline.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | Proof-first baseline for TRA-15-A: longhorn-manager failure matrix, kubelet `not a shared mount` events on `gabriel-pc`, and direct host `findmnt` propagation evidence |
| [2026-02-24-tra-14-crowdsec-proof-recheck-snapshot.md](2026-02-24-tra-14-crowdsec-proof-recheck-snapshot.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | Proof-first recheck for TRA-14 with node failure signature matrix, enrollment/LAPI evidence, controlled churn observations, and 30+ minute post-churn stability evidence |
| [2026-02-24-speedtest-exporter-deprecation-research-and-decision.md](2026-02-24-speedtest-exporter-deprecation-research-and-decision.md) | 2026-02-24 | ✅ COMPLETED | 🟡 MEDIUM | Research-backed decision for deprecated speedtest exporter: current signal is stale/noisy with no active Prometheus value, so remove now and defer replacement to a separate trust/license-reviewed task |
| [2026-02-24-colab-local-runtime-gpu-traefik-rollout.md](2026-02-24-colab-local-runtime-gpu-traefik-rollout.md) | 2026-02-24 | ✅ COMPLETED | 🔴 HIGH | Colab local runtime rollout with GPU-tier routing and deterministic token; deployment, placement, and high-end-to-low-end fallback behavior validated |
| [2026-02-24-swarm-vip-path-instability-investigation.md](2026-02-24-swarm-vip-path-instability-investigation.md) | 2026-02-24 | 🔄 INVESTIGATING | 🔴 HIGH | Root-cause snapshot for node-specific Swarm VIP failure mode where one internal service VIP path times out on one node while direct task IP path remains healthy |
| [2026-02-24-tra-51-telegraf-migration-rollup-and-provenance.md](2026-02-24-tra-51-telegraf-migration-rollup-and-provenance.md) | 2026-02-24 | ✅ COMPLETED | 🟡 MEDIUM | TRA-51 completion rollup with managed-template state, live validation, rollback checkpoint, and latest-stable Telegraf version provenance |
| [2026-02-24-telegraf-docker-health-integration-validation-snapshot.md](2026-02-24-telegraf-docker-health-integration-validation-snapshot.md) | 2026-02-24 | ✅ COMPLETED | 🟡 MEDIUM | Final validation snapshot for Telegraf docker-health integration into Grafana + Prometheus alerts, including live rollout evidence and hostname-label regression fix |
| [2026-02-24-telegraf-monitoring-semantics-and-cutover-snapshot.md](2026-02-24-telegraf-monitoring-semantics-and-cutover-snapshot.md) | 2026-02-24 | ✅ COMPLETED | 🟡 MEDIUM | Approved semantic decision snapshot (`main-monitoring` for Telegraf collector, `main-uptime` for human status) plus template cutover state |
| [2026-02-24-telegraf-docker-health-metric-mapping.md](2026-02-24-telegraf-docker-health-metric-mapping.md) | 2026-02-24 | ✅ COMPLETED | 🟡 MEDIUM | Metric/query mapping snapshot from current container-health-exporter to Telegraf docker input, including PromQL translations and no-healthcheck caveats |
| [2026-02-24-docker-health-collector-community-evidence.md](2026-02-24-docker-health-collector-community-evidence.md) | 2026-02-24 | ✅ COMPLETED | 🟡 MEDIUM | Community evidence + official cross-check for cAdvisor vs Telegraf Docker health collection, with explicit facts/opinion boundary and migration risk notes |
| [2026-02-24-container-health-exporter-multi-arch-replacement-research.md](2026-02-24-container-health-exporter-multi-arch-replacement-research.md) | 2026-02-24 | ✅ COMPLETED | 🟡 MEDIUM | Multi-arch replacement research for Docker health exporter with manifest evidence, metric compatibility comparison, and migration/rollback recommendation |
| [2026-02-23-rebalance-stability-three-flips-gabriel-pc-rerun.md](2026-02-23-rebalance-stability-three-flips-gabriel-pc-rerun.md) | 2026-02-23 | ✅ COMPLETED | 🔴 HIGH | Conclusive 3-point rerun with mixed behavior (rebalance updates + cooldown skips), CSV/Python evidence, and quantified churn impact under active rebalance |
| [2026-02-23-rebalance-stability-three-flips-gabriel-pc.md](2026-02-23-rebalance-stability-three-flips-gabriel-pc.md) | 2026-02-23 | ✅ COMPLETED | 🔴 HIGH | Multi-point stability validation with 3 Gabriel-PC flips, CSV artifacts, and Python analysis showing cooldown-guarded flip handling remained non-disruptive |
| [2026-02-23-swarm-rebalance-node-flip-validation-gabriel-pc.md](2026-02-23-swarm-rebalance-node-flip-validation-gabriel-pc.md) | 2026-02-23 | ✅ COMPLETED | 🔴 HIGH | Live rebalance validation on ephemeral `Gabriel-PC` flip proving cluster-group constraint skips and per-service cooldown behavior, with global cooldown restored after deterministic test window |
| [2026-02-23-swarm-self-healing-runtime-validation-phase4.md](2026-02-23-swarm-self-healing-runtime-validation-phase4.md) | 2026-02-23 | ✅ COMPLETED | 🔴 HIGH | Live acceptance validation snapshot: one-by-one force-update convergence checks plus controlled bad-image rollback test confirming automatic rollback behavior |
| [2026-02-23-swarm-self-healing-runtime-rollout-phase3-storage.md](2026-02-23-swarm-self-healing-runtime-rollout-phase3-storage.md) | 2026-02-23 | ✅ COMPLETED | 🔴 HIGH | One-by-one storage runtime rollout for self-healing hardening with final convergence to `1/1` and restart-policy alignment on targeted storage services |
| [2026-02-23-swarm-self-healing-runtime-rollout-phase2.md](2026-02-23-swarm-self-healing-runtime-rollout-phase2.md) | 2026-02-23 | 🔄 IN PROGRESS | 🔴 HIGH | One-by-one runtime rollout for admin, monitoring, and Traefik services under self-healing hardening; services converged with known `container-health-exporter` arch mismatch unchanged |
| [2026-02-23-swarm-rebalance-runtime-rollout-and-debug-cleanup.md](2026-02-23-swarm-rebalance-runtime-rollout-and-debug-cleanup.md) | 2026-02-23 | ⚠️ PARTIALLY COMPLETED | 🔴 HIGH | Runtime rollout of `main-maintenance_ephemeral-rebalance` with cluster-group policy plus one-by-one cleanup of orphan `debug-*`/`diag-*` services |
| [2026-02-23-swarm-rebalance-cluster-group-policy-hardening.md](2026-02-23-swarm-rebalance-cluster-group-policy-hardening.md) | 2026-02-23 | 🔄 IN PROGRESS | 🔴 HIGH | Rebalance hardening aligned to label policy: removed service-tag targeting, enforced existing-label cluster-group matching, added cooldown and explicit decision logging |
| [2026-02-23-swarm-self-healing-policy-hardening-phase1.md](2026-02-23-swarm-self-healing-policy-hardening-phase1.md) | 2026-02-23 | 🔄 IN PROGRESS | 🔴 HIGH | Config hardening phase 1 for Swarm self-healing: restart policy alignment for always-on services and partial rollout guardrails, with compose validation completed and deploy pending |
| [2026-02-23-ephemeral-rebalance-rewrite-prerequisite-investigation.md](2026-02-23-ephemeral-rebalance-rewrite-prerequisite-investigation.md) | 2026-02-23 | ✅ DECIDED | 🟡 MEDIUM | Prerequisite decision for `ephemeral-rebalance` rewrite path: proceed with immediate shell hardening, defer Python/Go migration to a second phase with immutable image and canary strategy |
| [2026-02-23-swarm-critical-services-recovery-snapshot.md](2026-02-23-swarm-critical-services-recovery-snapshot.md) | 2026-02-23 | ⚠️ PARTIAL RECOVERY | 🔴 HIGH | Live Swarm incident snapshot: recovered critical `0/1` platform services to healthy state; remaining degraded services are diagnostic one-shots, ARM image mismatch for one global monitor replica, and known GPU volume conflict |
| [2026-02-22-k3s-traefik-port-remap-for-443-ownership.md](2026-02-22-k3s-traefik-port-remap-for-443-ownership.md) | 2026-02-22 | ✅ COMPLETED | 🔴 HIGH | Incident/change report for recovering Swarm Traefik ownership of `:443` by remapping K3s Traefik external exposure to `:8080/:8443`, with post-change TLS validation |
| [2026-02-22-k8s-gateway-api-primary-routing-decision.md](2026-02-22-k8s-gateway-api-primary-routing-decision.md) | 2026-02-22 | ✅ DECIDED | 🔴 HIGH | Routing architecture snapshot: Gateway API primary in Kubernetes, no Kubernetes Ingress for new routes, and Traefik CRDs reserved for advanced parity cases |
| [2026-02-21-minio-tiering-clean-reexecution-validation.md](2026-02-21-minio-tiering-clean-reexecution-validation.md) | 2026-02-21 | ✅ COMPLETED | 🔴 HIGH | Clean validation run for MinIO tiering reproducibility: removed existing lifecycle rule, verified empty state, re-applied via `cluster-utils`, and confirmed idempotence |
| [2026-02-21-minio-status-deprecation-and-admin-api.md](2026-02-21-minio-status-deprecation-and-admin-api.md) | 2026-02-21 | ✅ COMPLETED | 🔴 HIGH | MinIO routing recovery, admin API `v3`/`v4` compatibility validation, upstream maintenance/license signal snapshot, and decision to remain on current MinIO path |
| [2026-02-21-k3s-template-privacy-hardening.md](2026-02-21-k3s-template-privacy-hardening.md) | 2026-02-21 | ✅ COMPLETED | 🟡 MEDIUM | Commit-safe privacy hardening for K3s templates: generic node UFW route template and sanitized docs |
| [2026-02-20-k8s-storage-tiering-architecture-and-iam-plan.md](2026-02-20-k8s-storage-tiering-architecture-and-iam-plan.md) | 2026-02-20 | 🔄 IN PROGRESS | 🔴 HIGH | K8s storage-tiering architecture and IAM plan: Longhorn + Rook/CephFS RWX + existing Swarm MinIO hot tier with automatic transition to GCS cold tier |
| [2026-02-20-k3s-multi-manager-migration.md](2026-02-20-k3s-multi-manager-migration.md) | 2026-02-20 | ✅ COMPLETED | 🔴 HIGH | Migration of K3s control plane from single-manager to three managers with external Postgres datastore alignment and validation |
| [nvidia/INDEX.md](nvidia/INDEX.md) | 2026-02-18 | 🔄 INVESTIGATING | 🔴 HIGH | Master index for Gabriel-PC WSL GPU rendering investigation, source catalog, evidence map, and fact table |
| [2026-02-18-neko-wsl-nvenc-library-mount-analysis.md](2026-02-18-neko-wsl-nvenc-library-mount-analysis.md) | 2026-02-18 | 🔄 INVESTIGATING | 🔴 HIGH | Neko on `Gabriel-PC` (WSL) fails media pipeline due to missing in-container `libnvidia-encode`/`nvh264enc`; differential evidence vs host libs captured |
| [2026-02-18-neko-turn-webrtc-timeout-investigation.md](2026-02-18-neko-turn-webrtc-timeout-investigation.md) | 2026-02-18 | 🔄 INVESTIGATING | 🔴 HIGH | Neko login/signaling succeeds but WebRTC media session drops with `Disconnected / connection timeout`; TURN path analysis and transport-level evidence |
| [2026-02-02-netdata-dashboard-null-metrics.md](grafana-dashboard/issues/2026-02-02-netdata-dashboard-null-metrics.md) | 2026-02-02 | ✅ COMPLETED | 🟡 MEDIUM | Netdata Grafana dashboards reporting null metrics after import |
| [2026-01-24-uptime-monitoring-options.md](monitoring-health/2026-01-24-uptime-monitoring-options.md) | 2026-01-24 | ✅ COMPLETED | 🟡 MEDIUM | Uptime monitoring tool options and backup strategy (Prometheus hardening + backup monitors) |
| [2026-01-06-ragflow-postgres-connection-issue.md](2026-01-06-ragflow-postgres-connection-issue.md) | 2026-01-06 | ✅ RESOLVED | 🔴 CRITICAL | RAGFlow PostgreSQL SSL connection failures - configuration fixed, SSL enabled |
| [deployment-monitoring-validation.md](deployment-monitoring-validation.md) | 2025-01-02 | ✅ RESOLVED | 🔴 CRITICAL | Validation of deployment monitoring improvements for cluster-utils tool |
| [2026-01-07-grafana-dashboard-resolution-summary.md](grafana-dashboard/summaries/2026-01-07-grafana-dashboard-resolution-summary.md) | 2026-01-07 | ✅ COMPLETED | 🔴 CRITICAL | Complete resolution of Grafana dashboard "No data" issues with comprehensive system monitoring |
| [2026-01-20-postgres-tls-passthrough-verification.md](2026-01-20-postgres-tls-passthrough-verification.md) | 2026-01-20 | ✅ COMPLETED | 🟡 MEDIUM | Postgres TLS passthrough verification and end-to-end SSL check |

## Report Categories

### Monitoring Health
- Located in: `reports/monitoring-health/`
- Purpose: Service health, metrics, alerts analysis
- Index: `reports/monitoring-health/INDEX.md`
- **Latest Report:** [2026-01-24-uptime-monitoring-options.md](../monitoring-health/2026-01-24-uptime-monitoring-options.md) - Uptime monitoring tool options and backup strategy

### Performance Analysis
- Located in: `reports/performance/`
- Purpose: Resource utilization, bottleneck identification

### Security Audits
- Located in: `reports/security/`
- Purpose: Vulnerability assessments, compliance checks

### Capacity Planning
- Located in: `reports/capacity/`
- Purpose: Growth projections, scaling recommendations

### Grafana Dashboard Analysis
- Located in: `reports/grafana-dashboard/`
- Purpose: Dashboard configuration, metric compatibility, deployment issues
- Index: `reports/grafana-dashboard/INDEX.md`

### Debug Command Analysis
- Located in: `reports/debug/`
- Purpose: CLI tool improvements, pattern recognition enhancements
- Index: `reports/debug/INDEX.md`

### NVIDIA / WSL Investigation
- Located in: `reports/nvidia/`
- Purpose: Root-cause analysis for Gabriel-PC WSL GPU render path issues
- Index: `reports/nvidia/INDEX.md`

### Post-Mortems
- Located in: `post-mortem/`
- Purpose: Incident analysis, root cause, prevention

## Report Standards

All reports follow these standards:
- **Naming**: `YYYY-MM-DD-<descriptive-name>.md`
- **Structure**: Executive summary, detailed findings, recommendations, next steps
- **Updates**: Modify existing reports rather than creating duplicates
- **Cross-references**: Link related reports using relative markdown links
