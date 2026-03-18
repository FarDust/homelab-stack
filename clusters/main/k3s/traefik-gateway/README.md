# Traefik Gateway API Baseline (K3s)

This folder provides template-managed resources for a minimal Traefik Gateway API baseline.

## Files

- `traefik-gateway.env.template`: variables for baseline object names/hostnames
- `gateway-tls-certificate.yaml.template`: cert-manager certificate for Traefik Gateway `websecure` listener
- `traefik-helmchartconfig.yaml.template`: enables Traefik Kubernetes Gateway provider, keeps 8080/8443 remap, sets cross-namespace Gateway routing, and enables `websecure` listener
- `smoke-deployment.yaml.template`: `whoami` smoke backend
- `smoke-service.yaml.template`: smoke service
- `smoke-httproute.yaml.template`: smoke `HTTPRoute`

## Render

```bash
cp clusters/main/k3s/traefik-gateway/traefik-gateway.env.template \
  clusters/main/k3s/traefik-gateway/traefik-gateway.env

set -a
source .env
set +a

uv run cluster-utils k3s render-traefik-gateway-baseline --overwrite
```

## Apply

```bash
set -a
source .env
set +a

uv run cluster-utils k3s apply-traefik-gateway-baseline
```

## Verify

```bash
kubectl -n kube-system get deploy traefik -o jsonpath='{.spec.template.spec.containers[0].args}' | tr ' ' '\n' | grep kubernetesgateway
kubectl get gatewayclass,gateway,httproute -A
kubectl -n kube-system get certificate,secret | grep traefik-gateway-websecure-tls
kubectl -n kube-system get deploy,svc,httproute | grep traefik-gateway-smoke
```

Optional HTTP smoke check:

```bash
curl -sS -H "Host: gateway-smoke.local.example" http://127.0.0.1:8080/ | head -n 5
```

## Rollback

```bash
kubectl -n kube-system delete httproute traefik-gateway-smoke --ignore-not-found
kubectl -n kube-system delete svc traefik-gateway-smoke --ignore-not-found
kubectl -n kube-system delete deploy traefik-gateway-smoke --ignore-not-found
kubectl -n kube-system delete helmchartconfig traefik --ignore-not-found
```
