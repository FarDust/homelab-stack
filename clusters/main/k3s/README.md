# K3s Multi-Manager Definitions

This folder stores the K3s manager node configuration as YAML templates.
It is separate from Docker Swarm stack definitions in `stacks/`.

## Files

- `manager-primary-config.yaml.template`: primary manager config
- `manager-secondary-config.yaml.template`: secondary manager config
- `k3s.env.template`: variables used by templates
- `node-ufw-k8s-routes.sh.template`: generic node UFW route template for K8s pod/service forwarding
- `k3s-mount-propagation.service.template`: persistent mount-propagation systemd unit for Longhorn compatibility
- `coredns.env.template`: CoreDNS upstream resolver variables for cluster DNS path
- `nvidia-device-plugin.yaml.template`: managed NVIDIA device plugin DaemonSet template (GPU nodes only)
- `cert-manager/*`: managed cert-manager baseline (K3s HelmChart + issuer templates)
- `traefik-gateway/*`: managed Traefik Gateway API baseline (provider enablement + smoke route)
- `kfp/*`: managed Kubeflow Pipelines baseline (standalone install + pod-to-pod TLS)

## Render (Recommended)

```bash
cp clusters/main/k3s/k3s.env.template clusters/main/k3s/k3s.env
# edit clusters/main/k3s/k3s.env with real values

set -a
source .env
set +a

uv run cluster-utils k3s render-configs \
  --secondary-node manager-a \
  --secondary-node manager-b
```

Generated `*.yaml` files are gitignored.

Secondary node address variables:
- For each `--secondary-node <name>`, set `K3S_NODE_IP_<NAME>` and `K3S_NODE_ADVERTISE_ADDRESS_<NAME>`.
- `<NAME>` is normalized to uppercase with non-alphanumeric chars replaced by `_`.
- Example: `manager-edge-a` -> `K3S_NODE_IP_MANAGER_EDGE_A`.

## Apply On Each Node

```bash
sudo install -d -m 755 /etc/rancher/k3s
sudo install -m 600 clusters/main/k3s/<node>-config.yaml /etc/rancher/k3s/config.yaml
sudo systemctl restart k3s
```

For nodes running `k3s-agent`, switch unit type first as needed.

## Node UFW (K8s Pod/Service Forwarding)

On nodes with strict UFW forwarding defaults, apply interface-scoped route rules:

```bash
cp clusters/main/k3s/node-ufw-k8s-routes.sh.template clusters/main/k3s/node-ufw-k8s-routes.sh
chmod +x clusters/main/k3s/node-ufw-k8s-routes.sh
./clusters/main/k3s/node-ufw-k8s-routes.sh apply
```

Defaults target `cni0` and `flannel.1`.
Override interfaces when needed:

```bash
K3S_CNI_IFACE=cni0 K3S_OVERLAY_IFACE=flannel.1 ./clusters/main/k3s/node-ufw-k8s-routes.sh apply
```

## Persistent Mount Propagation (Longhorn)

Use this when Longhorn reports `... is not a shared mount` after node reboot/churn.
This keeps node runtime behavior consistent without per-node chart overrides.

Install on each Longhorn data node:

```bash
sudo install -m 644 clusters/main/k3s/k3s-mount-propagation.service.template \
  /etc/systemd/system/k3s-mount-propagation.service
sudo systemctl daemon-reload
sudo systemctl enable --now k3s-mount-propagation.service
```

Optional immediate refresh of node runtime:

```bash
sudo systemctl restart k3s || sudo systemctl restart k3s-agent
```

Verify on node:

```bash
findmnt -T / -o TARGET,PROPAGATION
findmnt -T /var/lib/kubelet -o TARGET,PROPAGATION
findmnt -T /var/lib/longhorn -o TARGET,PROPAGATION
```

Rollback:

```bash
sudo systemctl disable --now k3s-mount-propagation.service
sudo rm -f /etc/systemd/system/k3s-mount-propagation.service
sudo systemctl daemon-reload
```

## CoreDNS Upstream (Tailscale DNS)

Render a managed CoreDNS manifest from the live ConfigMap (with backup), replacing only
the `forward . ...` upstream directive.

```bash
cp clusters/main/k3s/coredns.env.template clusters/main/k3s/coredns.env
# edit clusters/main/k3s/coredns.env if needed

set -a
source .env
set +a

uv run cluster-utils k3s render-coredns-forward --overwrite
```

Apply and restart CoreDNS rollout:

```bash
set -a
source .env
set +a

uv run cluster-utils k3s apply-coredns-forward
```

Dry-run options:

```bash
uv run cluster-utils k3s render-coredns-forward --dry-run
uv run cluster-utils k3s apply-coredns-forward --dry-run
```

Rollback:

```bash
kubectl apply -f clusters/main/k3s/coredns-configmap.backup.yaml
kubectl -n kube-system rollout restart deploy/coredns
kubectl -n kube-system rollout status deploy/coredns --timeout=120s
```

## NVIDIA Device Plugin (Managed Manifest)

Render from template:

```bash
set -a
source .env
set +a

uv run cluster-utils k3s render-nvidia-device-plugin --overwrite
```

Apply and wait for DaemonSet rollout:

```bash
set -a
source .env
set +a

uv run cluster-utils k3s apply-nvidia-device-plugin
```

Dry-run options:

```bash
uv run cluster-utils k3s render-nvidia-device-plugin --dry-run
uv run cluster-utils k3s apply-nvidia-device-plugin --dry-run
```

## Cert-Manager Baseline

Use the template-managed flow in:

```bash
clusters/main/k3s/cert-manager/README.md
```

## Traefik Gateway API Baseline

Use the template-managed flow in:

```bash
clusters/main/k3s/traefik-gateway/README.md
```

## Kubeflow Pipelines Baseline (Pod-to-Pod TLS)

Use the template-managed flow in:

```bash
clusters/main/k3s/kfp/README.md
```

## Verify

```bash
kubectl get nodes -o wide
kubectl -n default get endpoints kubernetes -o wide
kubectl -n longhorn-system run dns-check --image=busybox:1.36 --restart=Never --rm -it -- nslookup kubernetes.default.svc.cluster.local
```
