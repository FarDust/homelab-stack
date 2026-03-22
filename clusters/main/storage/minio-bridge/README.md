# MinIO Bridge (CephFS -> MinIO)

This folder provides commit-safe templates for the Kubernetes bridge that syncs data from CephFS RWX to the existing Swarm MinIO hot bucket.

## Files

- `minio-bridge.env.template`: render variables (non-secret defaults)
- `namespace.yaml.template`: target namespace
- `cephfs-pvc.yaml.template`: shared RWX PVC for producers + sync
- `minio-secret.yaml.template`: MinIO connection secret (rendered locally)
- `minio-sync-cronjob.yaml.template`: periodic sync job

## Render (local only)

```bash
cp clusters/main/storage/minio-bridge/minio-bridge.env.template \
  clusters/main/storage/minio-bridge/minio-bridge.env
# edit clusters/main/storage/minio-bridge/minio-bridge.env

source .env
uv run cluster-utils storage render-minio-sync
```

Rendered files are gitignored.

## Apply

```bash
source .env
uv run cluster-utils storage apply-minio-sync
```

Then label one node for sync egress:

```bash
kubectl label node <node-name> storage.sync/minio-egress=true --overwrite
```

## Verify

```bash
kubectl -n ml-validation get pvc,cronjob
kubectl -n ml-validation get jobs --sort-by=.metadata.creationTimestamp
kubectl -n ml-validation logs job/<latest-job-name>
```

## Notes

- MinIO credentials default to `.env` values (`RAGFLOW_MINIO_USER` / `RAGFLOW_MINIO_PASSWORD`) unless overridden in `minio-bridge.env`.
- Keep producers and sync CronJob in the same namespace because PVCs are namespaced.
