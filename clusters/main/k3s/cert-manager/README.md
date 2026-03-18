# Cert-Manager Baseline (K3s)

This folder provides template-managed resources for cert-manager in K3s.

## Files

- `cert-manager.env.template`: version and email placeholders
- `cert-manager-helmchart.yaml.template`: K3s HelmChart resource
- `clusterissuer-selfsigned.yaml.template`: baseline internal issuer
- `clusterissuer-cloudflare.yaml.template`: optional Cloudflare ACME issuer
- `cloudflare-api-token-secret.yaml.template`: optional Cloudflare API token secret

## Render

```bash
cp clusters/main/k3s/cert-manager/cert-manager.env.template \
  clusters/main/k3s/cert-manager/cert-manager.env

set -a
source .env
source clusters/main/k3s/cert-manager/cert-manager.env
set +a

envsubst < clusters/main/k3s/cert-manager/cert-manager-helmchart.yaml.template \
  > clusters/main/k3s/cert-manager/cert-manager-helmchart.rendered.yaml
envsubst < clusters/main/k3s/cert-manager/clusterissuer-selfsigned.yaml.template \
  > clusters/main/k3s/cert-manager/clusterissuer-selfsigned.rendered.yaml
```

Optional Cloudflare realization:

```bash
envsubst < clusters/main/k3s/cert-manager/cloudflare-api-token-secret.yaml.template \
  > clusters/main/k3s/cert-manager/cloudflare-api-token-secret.rendered.yaml
envsubst < clusters/main/k3s/cert-manager/clusterissuer-cloudflare.yaml.template \
  > clusters/main/k3s/cert-manager/clusterissuer-cloudflare.rendered.yaml
```

## Apply

```bash
kubectl apply -f clusters/main/k3s/cert-manager/cert-manager-helmchart.rendered.yaml
kubectl -n cert-manager rollout status deploy/cert-manager --timeout=240s
kubectl -n cert-manager rollout status deploy/cert-manager-webhook --timeout=240s
kubectl -n cert-manager rollout status deploy/cert-manager-cainjector --timeout=240s

kubectl apply -f clusters/main/k3s/cert-manager/clusterissuer-selfsigned.rendered.yaml
```

## Verify

```bash
kubectl get ns cert-manager
kubectl get crd certificates.cert-manager.io issuers.cert-manager.io clusterissuers.cert-manager.io
kubectl -n cert-manager get deploy
kubectl get clusterissuer
```

## Rollback

```bash
kubectl delete clusterissuer local-selfsigned --ignore-not-found
kubectl -n kube-system delete helmchart cert-manager --ignore-not-found
kubectl delete ns cert-manager --ignore-not-found
```
