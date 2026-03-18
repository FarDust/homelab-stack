# Longhorn Storage Definitions

This folder stores commit-safe Longhorn templates for cluster storage policy.
It contains generic templates only and no host-identifiable values.

## Files

- `storage.env.template`: shared variables for rendering
- `longhorn-settings.yaml.template`: Longhorn global settings
- `longhorn-node-policy.yaml.template`: per-node scheduling policy
- `storageclass-defaults.sh.template`: enforce single default StorageClass

## Render

```bash
cp clusters/main/storage/longhorn/storage.env.template clusters/main/storage/longhorn/storage.env
# edit clusters/main/storage/longhorn/storage.env

set -a
source clusters/main/storage/longhorn/storage.env
set +a

envsubst < clusters/main/storage/longhorn/longhorn-settings.yaml.template \
  > clusters/main/storage/longhorn/longhorn-settings.yaml

envsubst < clusters/main/storage/longhorn/longhorn-node-policy.yaml.template \
  > clusters/main/storage/longhorn/longhorn-node-policy.yaml
```

Rendered files are gitignored.

## Apply

```bash
kubectl apply -f clusters/main/storage/longhorn/longhorn-settings.yaml
kubectl apply -f clusters/main/storage/longhorn/longhorn-node-policy.yaml
```

To enforce default StorageClass policy:

```bash
cp clusters/main/storage/longhorn/storageclass-defaults.sh.template \
  clusters/main/storage/longhorn/storageclass-defaults.sh
chmod +x clusters/main/storage/longhorn/storageclass-defaults.sh
./clusters/main/storage/longhorn/storageclass-defaults.sh
```
