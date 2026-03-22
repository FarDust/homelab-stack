# Swarm Node Labels

This is the canonical list of Docker Swarm node labels used for placement constraints in this repo.

## Conventions

- Labels are string key/value pairs.
- Keys use dot-separated namespaces (e.g., `storage.manager`, `gpu.class`).
- Boolean labels should use `true`/`false` strings.
- Constraint syntax is `node.labels.<key> == <value>`.

## Tagging Policy Guardrails

- Do not introduce new labels/tags without explicit approval.
- Use only labels already defined in this document.
- Target scheduling/rebalance behavior by cluster label groups (node label combinations).
- Do not add service-specific targeting tags when existing node labels can express the group.
- Do not use labels as workarounds for unrelated root causes.
- Placement constraints must match the real scheduling reason (semantic correctness).

## Semantic Correctness Rules

- Use node labels only for what they represent.
- If the root cause is architecture mismatch, use `node.platform.arch` or a multi-arch image strategy, not topology labels.
- If the root cause is topology/policy scope, use `site.class`, `site.name`, `region`, or `instance.class`.
- If the root cause is lifecycle stability, use `node.ephemeral`.
- If the root cause is capacity/performance class, use `load.tier` or `storage.manager`.

## Disallowed Mappings (Examples)

- Do not use `site.class` to fix CPU architecture incompatibility.
- Do not use `instance.class` to fix image manifest incompatibility.
- Do not use `region` to fix runtime dependency/library errors.
- Do not use `swarm.leader` as a generic “make it work” pin for non-control-plane services.

## Targeting Decision Flow

```text
[Need targeting rule]
        |
        v
[What is the root cause category?]
        |
        v
[Choose label/constraint family that matches semantics]
        |
        v
[Can existing labels express it?]
   | Yes                         | No
   v                             v
[Use existing node-label       [STOP]
 group combinations]           [Request approval for new label]
        |
        v
[Apply at cluster-group scope]
        |
        v
[Avoid per-service tag taxonomy]
        |
        v
[Validate and document]
```

## Current labels (in use or observed)

| Label key | Expected values | Purpose | Example constraint |
| --- | --- | --- | --- |
| `swarm.leader` | `true` | Pin a service to the swarm leader. | `node.labels.swarm.leader == true` |
| `AVX` | `true` / `false` | CPU AVX capability required (use `!= false` to allow unset). | `node.labels.AVX != false` |
| `gpu` | `true` / `false` | GPU availability. | `node.labels.gpu == true` |
| `gpu.class` | `high-end` / `low-end` | GPU tier for workload sizing. | `node.labels.gpu.class == high-end` |
| `gpu.model` | model string (e.g., `rtx5090`) | Informational GPU model tag. | `node.labels.gpu.model == rtx5090` |
| `gpu.vram` | VRAM string (e.g., `32gb`) | Informational GPU memory size. | `node.labels.gpu.vram == 32gb` |
| `storage.manager` | `true` / `false` | High-performance storage node. | `node.labels.storage.manager == true` |
| `load.tier` | `light` / `heavy` | Capacity tier for scheduling. | `node.labels.load.tier == heavy` |
| `node.ephemeral` | `true` / `false` | Short-lived nodes (avoid for stateful services). | `node.labels.node.ephemeral != true` |

## New labels (selected)

| Label key | Expected values | Purpose | Example constraint |
| --- | --- | --- | --- |
| `site.class` | `datacenter` / `cloud` | Distinguish on-prem DC vs cloud environments. | `node.labels.site.class == cloud` |
| `instance.class` | `metal` / `virtual` | Distinguish bare metal vs VM instances. | `node.labels.instance.class == virtual` |
| `site.name` | `home` / `dc1` / `oracle` / `gcp` | Identify the physical site or provider. | `node.labels.site.name == oracle` |
| `region` | Provider region code (cloud) or short site code (on-prem). Examples: `southamerica-west1`, `sa-east-1`, `chilecentral`, `sa-santiago-1`, `scl`. | Regional affinity and failover targeting. | `node.labels.region == sa-santiago-1` |

## Label management examples

```sh
# Add labels to a node
docker node update \
  --label-add site.class=cloud \
  --label-add instance.class=virtual \
  --label-add site.name=oracle \
  --label-add region=sa-east-1 \
  instance-20220415-1709

# Remove a label from a node
docker node update --label-rm site.class instance-20220415-1709

# Inspect labels
docker node inspect instance-20220415-1709 --format '{{json .Spec.Labels}}'

# List all nodes and their labels (table)
for n in $(docker node ls -q); do
  name=$(docker node inspect "$n" --format '{{.Description.Hostname}}')
  echo "=== $name ==="
  docker node inspect "$n" --format '{{json .Spec.Labels}}' | jq -r 'to_entries | sort_by(.key) | .[] | "  \(.key)=\(.value)"'
  echo
done
```

## Labels per node (snapshot)

Use the inspect command above to refresh. Example snapshot:

| Node | site.class | site.name | load.tier | gpu | node.ephemeral | Notes |
|------|------------|-----------|-----------|-----|----------------|-------|
| Gabriel-PC | datacenter | home | heavy | true | true | On-prem, GPU |
| fardustdev | datacenter | home | light | — | — | On-prem, swarm.leader, storage.manager |
| frost-fang | datacenter | home | heavy | true | — | On-prem, storage.manager |
| instance-20220415-1702 | **cloud** | oracle | light | — | true | Oracle cloud |
| instance-20220415-1709 | **cloud** | oracle | light | — | true | Oracle cloud |
| instance-20220415-1710 | **cloud** | oracle | light | — | true | Oracle cloud |

To keep torrent-related workloads off cloud providers, use `node.labels.site.class != cloud` in placement constraints.

## Placement examples

```yaml
deploy:
  placement:
    constraints:
      - node.labels.site.class == cloud
      - node.labels.instance.class == virtual
      - node.labels.site.name == oracle
      - node.labels.region == sa-east-1
      - node.labels.load.tier == light
      - node.labels.node.ephemeral != true
```
