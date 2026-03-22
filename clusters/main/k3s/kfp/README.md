# Kubeflow Pipelines Baseline (K3s)

This folder provides template-managed resources for a standalone KFP install
with cert-manager-backed pod-to-pod TLS.

## Files

- `kfp.env.template`: KFP version and namespace placeholders
- `namespace.yaml.template`: KFP namespace manifest template
- `seaweedfs-securitycontext-patch.yaml.template`: storage permission baseline for SeaweedFS on RWX/PVC backends
- `ui-httproute.yaml.template`: Traefik Gateway API route for the KFP UI
- `ui-traefik-networkpolicy.yaml`: allow Traefik ingress to the KFP UI service pods

## Render

```bash
cp clusters/main/k3s/kfp/kfp.env.template \
  clusters/main/k3s/kfp/kfp.env

set -a
source .env
set +a

uv run cluster-utils k3s render-kfp-baseline --overwrite

set -a
source .env
source clusters/main/k3s/kfp/kfp.env
set +a

envsubst < clusters/main/k3s/kfp/ui-httproute.yaml.template \
  > clusters/main/k3s/kfp/ui-httproute.yaml
```

## Apply

```bash
set -a
source .env
set +a

uv run cluster-utils k3s apply-kfp-baseline

kubectl apply -f clusters/main/k3s/kfp/ui-httproute.yaml
kubectl apply -f clusters/main/k3s/kfp/ui-traefik-networkpolicy.yaml
```

## Verify

```bash
kubectl get crd pipelines.kubeflow.org
kubectl -n kubeflow get deploy,svc,pods
kubectl -n kubeflow rollout status deploy/ml-pipeline --timeout=600s
kubectl -n kubeflow rollout status deploy/ml-pipeline-ui --timeout=600s
kubectl -n kubeflow rollout status deploy/ml-pipeline-persistenceagent --timeout=600s
kubectl -n kubeflow get httproute "${KFP_UI_ROUTE_NAME}"
kubectl -n kubeflow get networkpolicy allow-traefik-to-kfp-ui
```

## Rollback

```bash
# Uses the same KFP_VERSION as kfp.env
set -a
source clusters/main/k3s/kfp/kfp.env
set +a

kubectl delete -k "github.com/kubeflow/pipelines/manifests/kustomize/env/cert-manager/platform-agnostic-standalone-tls?ref=${KFP_VERSION}" --ignore-not-found
kubectl delete -k "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=${KFP_VERSION}" --ignore-not-found
kubectl delete namespace kubeflow --ignore-not-found
```

## Sources

- Kubeflow Pipelines operator install guide (includes pod-to-pod TLS):
  https://www.kubeflow.org/docs/components/pipelines/operator-guides/installation/
