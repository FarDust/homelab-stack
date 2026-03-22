# Rook-Ceph Definitions

This folder stores commit-safe templates for Rook-Ceph and CephFS (RWX).

## Files

- `rook-ceph.env.template`: render variables
- `operator-values.yaml.template`: Helm values for `rook-ceph` operator chart
- `cluster-values.yaml.template`: Helm values for `rook-ceph-cluster` chart

## Render

```bash
cp clusters/main/storage/rook-ceph/rook-ceph.env.template clusters/main/storage/rook-ceph/rook-ceph.env
# edit clusters/main/storage/rook-ceph/rook-ceph.env

set -a
source clusters/main/storage/rook-ceph/rook-ceph.env
set +a

envsubst < clusters/main/storage/rook-ceph/operator-values.yaml.template \
  > clusters/main/storage/rook-ceph/operator-values.yaml

envsubst < clusters/main/storage/rook-ceph/cluster-values.yaml.template \
  > clusters/main/storage/rook-ceph/cluster-values.yaml
```

Rendered files are gitignored.

## Apply

```bash
helm repo add rook-release https://charts.rook.io/release
helm repo update

kubectl create namespace "${ROOK_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install "${ROOK_RELEASE_NAME}" rook-release/rook-ceph \
  --namespace "${ROOK_NAMESPACE}" \
  --version "${ROOK_CHART_VERSION}" \
  -f clusters/main/storage/rook-ceph/operator-values.yaml

helm upgrade --install "${ROOK_CLUSTER_RELEASE_NAME}" rook-release/rook-ceph-cluster \
  --namespace "${ROOK_NAMESPACE}" \
  --version "${ROOK_CHART_VERSION}" \
  -f clusters/main/storage/rook-ceph/cluster-values.yaml
```

## Verify

```bash
kubectl -n "${ROOK_NAMESPACE}" get pods
kubectl -n "${ROOK_NAMESPACE}" get cephcluster,cephfilesystem
kubectl get storageclass | grep "${ROOK_CEPHFS_SC_NAME}"
```
