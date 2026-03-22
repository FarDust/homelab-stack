# Prometheus Adapter (Volcano Load-Aware Metrics)

Pinned Prometheus Adapter baseline for Volcano `usage` plugin custom node metrics.

## Version

- Chart: `prometheus-community/prometheus-adapter`
- Version: `5.3.0`

## Install

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install prometheus-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  --create-namespace \
  --version 5.3.0 \
  -f clusters/main/k3s/prometheus-adapter/values.yaml
```

## Purpose

- Expose `custom.metrics.k8s.io` node metrics for Volcano's upstream `prometheus_adaptor` mode.
- Reuse the existing Swarm Prometheus `node-exporter` data.
- Avoid Docker socket discovery and static IP scrape targets.

## Verify

```bash
kubectl get apiservices | rg custom.metrics.k8s.io
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1 | jq .
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1/nodes/*/node_cpu_usage_avg | jq .
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1/nodes/*/node_memory_usage_avg | jq .
```

## Notes

- The adapter rules derive node names from `node_uname_info.nodename`.
- This keeps the existing Swarm monitoring path intact and satisfies Volcano's requirement for node-scoped usage metrics.
