# Grafana Helm Chart

Grafana deployment for Kubernetes with GCS backend storage, coexisting with Docker Swarm deployment.

## Architecture

- **Namespace**: `main-monitoring` (matches folder structure)
- **Storage**: GCS FUSE CSI driver (shared with Docker Swarm)
- **Database**: PostgreSQL (shared with Docker Swarm)
- **Configs**: References existing files in `stacks/main/configs/grafana/` (no duplication)
- **Secrets**: External secrets (must be created before deployment)

## Prerequisites

1. **GCS FUSE CSI Driver** installed in cluster
   ```bash
   kubectl apply -f https://github.com/GoogleCloudPlatform/gcs-fuse-csi-driver/releases/latest/download/gcs-fuse-csi-driver.yaml
   ```

2. **Traefik** with IngressRoute CRD support

3. **Authelia middleware** in `main-traefik` namespace

4. **PostgreSQL** accessible from cluster (shared with Swarm)

5. **Secrets created** in `main-monitoring` namespace

6. **Environment variables** sourced from `.env` file

## Creating Secrets

Before deploying, create all required secrets:

```bash
# Source environment
source .env

# Create namespace
kubectl create namespace main-monitoring

# Create secrets
kubectl create secret generic grafana-admin-password \
  --from-file=password=secrets/grafana/admin_password \
  -n main-monitoring

kubectl create secret generic grafana-database-password \
  --from-file=password=secrets/grafana/postgres_password \
  -n main-monitoring

kubectl create secret generic grafana-google-oauth \
  --from-file=client_secret=secrets/google/google_oauth_secret \
  -n main-monitoring

kubectl create secret generic grafana-smtp-password \
  --from-file=password=secrets/sendgrid/smtp_password \
  -n main-monitoring
```

## Deployment

### 1. Source Environment Variables

```bash
cd /path/to/repo
source .env
```

### 2. Deploy with Helm

```bash
helm install grafana clusters/main/monitoring/grafana \
  --namespace main-monitoring \
  --create-namespace \
  --set ingress.host="${DOMAIN_NAME}" \
  --set persistence.gcs.bucketName="${GCS_SYNC_STORAGE_BUCKET}/grafana/data" \
  --set database.host="${GF_DATABASE_HOST}" \
  --set database.name="${GF_POSTGRES_DB}" \
  --set database.user="${GF_POSTGRES_USER}" \
  --set auth.google.clientId="${GOOGLE_CLIENT_ID}" \
  --set smtp.user="${SMTP_USER}" \
  --set smtp.fromAddress="${SMTP_FROM}" \
  --set rendering.callbackUrl="https://grafana.${DOMAIN_NAME}/" \
  --set serverDomain="grafana.${DOMAIN_NAME}" \
  --set serverRootUrl="https://grafana.${DOMAIN_NAME}/"
```

### 3. Verify Deployment

```bash
# Check pods
kubectl get pods -n main-monitoring

# Check services
kubectl get svc -n main-monitoring

# Check ingress
kubectl get ingressroute -n main-monitoring

# Check PVC and PV
kubectl get pvc,pv -n main-monitoring
```

## Configuration

### Environment Variables Used

From `.env` file:
- `DOMAIN_NAME`: Domain for ingress
- `GCS_SYNC_STORAGE_BUCKET`: GCS bucket path
- `GF_DATABASE_HOST`: PostgreSQL host
- `GF_POSTGRES_DB`: Database name
- `GF_POSTGRES_USER`: Database user
- `GOOGLE_CLIENT_ID`: Google OAuth client ID
- `SMTP_USER`: SMTP username
- `SMTP_FROM`: SMTP from address

### External Config Files

The chart embeds configs from `stacks/main/configs/grafana/` into ConfigMaps using Helm's `.Files.Get`:
- Datasources: Loaded into ConfigMap from `datasource.yml`
- Dashboard config: Loaded into ConfigMap from `dashboard.yml`
- Dashboards: All JSON files loaded as binary data in ConfigMap

Configs are read at Helm install/upgrade time, ensuring single source of truth.

## Coexistence with Docker Swarm

Both deployments share:
- **GCS bucket**: Same path for persistent data
- **PostgreSQL**: Same database instance
- **Config files**: Reference same source files (no sync needed)

## Updating

### Update Deployment

```bash
source .env

helm upgrade grafana clusters/main/monitoring/grafana \
  --namespace main-monitoring \
  --set ingress.host="${DOMAIN_NAME}" \
  --set persistence.gcs.bucketName="${GCS_SYNC_STORAGE_BUCKET}/grafana/data" \
  # ... (same --set flags as install)
```

### Update Configs

Configs are embedded into ConfigMaps at Helm install/upgrade time. To update:

1. Modify files in `stacks/main/configs/grafana/`
2. Run Helm upgrade:
   ```bash
   source .env
   helm upgrade grafana clusters/main/monitoring/grafana \
     --namespace main-monitoring \
     --set ingress.host="${DOMAIN_NAME}" \
     --set persistence.gcs.bucketName="${GCS_SYNC_STORAGE_BUCKET}/grafana/data" \
     # ... (same --set flags as install)
   ```

The upgrade will regenerate ConfigMaps with updated content and restart pods.

## Troubleshooting

### Check Logs
```bash
kubectl logs -f deployment/grafana -n main-monitoring
```

### Check GCS Mount
```bash
kubectl exec -it deployment/grafana -n main-monitoring -- ls -la /var/lib/grafana
```

### Check Config Mounts
```bash
kubectl exec -it deployment/grafana -n main-monitoring -- cat /etc/grafana/provisioning/datasources/datasource.yml
```

### Database Connection
```bash
kubectl exec -it deployment/grafana -n main-monitoring -- env | grep GF_DATABASE
```

## Uninstall

```bash
helm uninstall grafana -n main-monitoring
kubectl delete namespace main-monitoring
```

**Note**: PersistentVolume may need manual cleanup if retention policy is set to Retain.
