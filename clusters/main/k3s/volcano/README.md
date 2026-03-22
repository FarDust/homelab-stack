# Volcano

Pinned Volcano installation baseline for the homelab scheduler-platform evaluation.

## Version

- Chart: `volcano-sh/volcano`
- Version: `1.14.1`

## Install

```bash
helm repo add volcano-sh https://volcano-sh.github.io/helm-charts
helm repo update
helm upgrade --install volcano volcano-sh/volcano \
  --namespace volcano-system \
  --create-namespace \
  --version 1.14.1 \
  -f clusters/main/k3s/volcano/values.yaml
```

## Load-Aware Scheduling

- The Helm values enable Volcano's upstream `usage` plugin in `prometheus_adaptor` mode.
- This depends on `prometheus-adapter` exposing:
  - `node_cpu_usage_avg`
  - `node_memory_usage_avg`
- Those custom node metrics are derived from the existing Swarm Prometheus `node-exporter` data by joining `node_uname_info.nodename`.
- Ordinary workloads still keep the default scheduler unless they set `spec.schedulerName: volcano`.

## Load-Aware Rebalancing

```bash
kubectl apply -f clusters/main/k3s/volcano/volcano-descheduler.yaml
```

- The descheduler manifest is kept minimal and upstream-shaped because the Volcano Helm chart does not bundle descheduler support.
- Image is pinned instead of using upstream `latest`.

## Verify

```bash
kubectl -n volcano-system get pods
kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations | rg volcano
kubectl get crd | rg 'volcano|podgroups|queues|vcjobs'
kubectl -n volcano-system get httproute
```

## Notes

- Volcano is installed first as a controlled scheduler-platform experiment.
- Default Kubernetes scheduling should remain unchanged for ordinary workloads that do not set `spec.schedulerName: volcano`.
- Initial adoption should stay narrow; do not introduce broad queue/policy changes in the first pass.
- Keep `custom.metrics_enable=false` unless you explicitly want Volcano's bundled in-cluster Grafana/Prometheus NodePorts. The existing homelab monitoring stack should scrape Volcano metrics instead.
- Volcano metrics are routed through the k3s Traefik Gateway on `:8443`, not scraped via raw Kubernetes service or pod IPs.
- Current routed hostnames (replace with your domain):
  - `volcano-scheduler.${LOCAL_DOMAIN}:8443`
  - `volcano-controllers.${LOCAL_DOMAIN}:8443`

## Uninstall

```bash
helm uninstall volcano -n volcano-system
kubectl delete namespace volcano-system --ignore-not-found
```

Review CRDs/webhook state before considering the uninstall complete.
