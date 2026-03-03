# 2026-03-03 TRA-217 OpenHands K3s Research Gate

- Timestamp (UTC): 2026-03-03T14:58:26Z
- Parent: `TRA-215`
- Child: `TRA-217`
- Scope: research/design gate only, no deployment changes

## Executive Summary

The requested target shape, "OpenHands on the existing K3s cluster connected to the existing Keycloak and using `cluster-utils` to create the appropriate DB user", is not currently justified for the MIT-licensed OpenHands OSS product.

Primary-source review shows:

1. upstream positions OSS OpenHands as a Local GUI / local-serving product;
2. the default and recommended sandbox remains Docker-based;
3. Kubernetes self-hosting is attached to OpenHands Enterprise / OpenHands Cloud, not the OSS Local GUI;
4. multi-user support, RBAC, and hosted-style integrations are explicitly attached to Cloud, not to the OSS Local GUI.

Recommendation:

1. do **not** proceed with `TRA-215` as an OSS "shared K3s app with Keycloak + shared Postgres" implementation;
2. require human approval of one of these two pivots before implementation:
   - a constrained **single-user OSS** K3s experiment with ingress auth only and no shared-Postgres requirement;
   - a **licensed Cloud / Enterprise** evaluation path if true K8s-native multi-user + Keycloak semantics are required.

## Repo Baseline

### Existing OpenHands shape in this repo

Source: `stacks/llms/agents.yml`

- current repo baseline runs `openhands` in Swarm;
- it mounts `/var/run/docker.sock`;
- it mounts persistent OpenHands state and multiple sandbox workspaces;
- it is manager-constrained;
- it exposes only the web UI through Traefik;
- it does **not** define:
  - an app database,
  - Keycloak integration,
  - user/RBAC mapping.

This matches a Docker-local execution model, not a K3s-native application design.

### Prior repo conclusion already on record

Source: `reports/2026-02-25-tra-125-openhands-platform-fit-research.md`

That report concluded K8s migration is non-trivial because OpenHands behavior is runtime-driven and Docker-oriented, not a simple stateless web app move. That conclusion remains consistent with current upstream docs.

## Upstream Evidence Reviewed

### OSS product positioning

OpenHands upstream README currently distinguishes:

1. **OpenHands Local GUI**:
   - "Use the Local GUI for running agents on your laptop."
2. **OpenHands Cloud**:
   - includes "Multi-user support", "RBAC and permissions", and collaboration features.
3. **OpenHands Enterprise**:
   - enterprises can self-host OpenHands Cloud "via Kubernetes".

Sources:

- https://github.com/OpenHands/OpenHands

### Runtime / sandbox model

Upstream sandbox documentation says:

1. Docker sandbox is the "default and recommended option for most users";
2. OpenHands runtime architecture uses Docker containers for execution;
3. the sandbox can mount host paths read-write via `SANDBOX_VOLUMES`.

Sources:

- Docker sandbox docs:
  - https://docs.openhands.dev/openhands/usage/sandboxes/docker
- Runtime architecture docs:
  - https://docs.openhands.dev/openhands/usage/architecture/runtime

### Remote sandbox option

Upstream docs also describe a remote sandbox mode:

- intended for managed deployments and advanced self-hosted setups;
- requires a runtime API URL and API key;
- it is not a drop-in replacement already present in this repo.

Sources:

- https://docs.openhands.dev/openhands/usage/sandboxes/remote
- https://docs.openhands.dev/openhands/usage/sandboxes/overview

### Kubernetes self-hosted path

The current upstream self-hosted Kubernetes repo is `OpenHands-Cloud`, which is:

1. licensed under the Polyform Free Trial License, not open source;
2. explicitly described as Helm charts for installing OpenHands Cloud in your own Kubernetes cluster.

Source:

- https://github.com/All-Hands-AI/OpenHands-Cloud

### Versioning / image namespace drift

Upstream also notes the org transfer from `All-Hands-AI` to `OpenHands`, and future GHCR images / Helm charts move to `ghcr.io/openhands/...`.

Source:

- https://github.com/OpenHands/OpenHands/issues/11376

This matters because the repo's current Swarm template still uses `docker.all-hands.dev/all-hands-ai/...`, which is a legacy path and should not be assumed to be the long-term pinning strategy.

## Findings

### 1. The requested OSS shape does not match upstream product boundaries

This is the main finding.

The request assumes a K3s-hosted app with:

1. existing Keycloak integration,
2. shared DB user provisioning,
3. a normal K8s application rollout under repo template policy.

But upstream separates these concerns differently:

1. OSS Local GUI is positioned as local / self-run software;
2. Cloud carries multi-user and RBAC;
3. Enterprise is the self-hosted Kubernetes path.

Inference from sources:

Implementing OSS OpenHands on K3s with Keycloak in front would not automatically make it equivalent to the Cloud / Enterprise product shape. It would still be the OSS Local GUI unless additional upstream-supported components are introduced.

### 2. Docker-sandbox assumptions remain the default

Upstream still recommends Docker sandbox by default, and the runtime architecture still centers on Docker container launch and runtime image construction.

Implication for this cluster:

Any OSS deployment that tries to preserve current OpenHands behavior needs one of:

1. host Docker socket access from the app workload,
2. a remote sandbox API service,
3. a different sandbox provider with materially different operational behavior.

The current repo already flagged Docker-socket exposure as a security concern in `TRA-125`, and that concern remains valid.

### 3. Existing Keycloak can gate access, but not by itself provide app-native multi-user semantics

Repo evidence from BeeAI shows the cluster can already:

1. provision Keycloak clients with `cluster-utils keycloak`;
2. map OIDC settings into a K3s app;
3. handle reverse-proxy trust requirements.

Sources:

- `reports/2026-03-03-tra-193-beeai-external-oidc-keycloak.md`
- `cluster-utils/src/cluster_utils/commands/keycloak.py`

However, I found no primary-source evidence that OSS OpenHands Local GUI exposes the same app-native multi-user/RBAC contract that Cloud advertises.

Inference:

Keycloak could be used as **perimeter auth** in front of an OSS OpenHands UI, but that is not equivalent to supported in-app user separation or RBAC.

### 4. Shared Postgres is not currently justified for OSS OpenHands

Repo evidence:

1. current Swarm OpenHands service has no DB;
2. current upstream Local GUI docs reviewed here do not establish a required external Postgres contract;
3. no repo-local OpenHands K8s package currently defines such a DB contract.

Inference:

The requirement to create a shared Postgres DB user via `cluster-utils db create-user` is not yet evidence-backed for OSS OpenHands. That requirement may make sense for Cloud / Enterprise or for a future custom deployment pattern, but it is not currently justified from the sources reviewed.

This is materially different from BeeAI, where the chart and migrations clearly required external Postgres.

### 5. Remote sandbox is the only upstream-shaped path that meaningfully reduces Docker-socket coupling

Upstream now documents remote sandbox mode and an API-based remote workspace. That is the only source-reviewed path here that points away from direct local Docker-socket dependence.

But in this repo today:

1. there is no existing runtime API service for OpenHands;
2. there is no commit-safe template package for such a service;
3. there is no `cluster-utils` support for provisioning it.

Inference:

A "proper" K3s-native OSS design would likely require building or adopting a remote sandbox service first, which is a materially larger platform project than "deploy OpenHands to K3s".

## Design Options

### Option A: Reject OSS K3s rollout for now

Description:

- keep OpenHands disabled or Swarm-only until there is a stronger upstream-supported self-hosted K8s OSS story.

Pros:

- best alignment with current upstream product boundaries;
- avoids inventing unsupported auth / DB semantics;
- avoids premature Docker-socket-on-K8s design debt.

Cons:

- no new OpenHands capability on the K3s cluster yet.

Assessment:

- this is the safest option.

### Option B: Approve only a constrained single-user OSS experiment on K3s

Description:

- treat OpenHands as a single-user Local GUI style service on K3s;
- expose it behind perimeter auth using existing Keycloak-aware ingress components;
- do **not** require shared Postgres unless new evidence justifies it;
- keep state local/PVC-based;
- document clearly that this is not Cloud-like multi-user OpenHands.

Pros:

- gives a bounded proof-of-concept path;
- reuses existing K3s template and Keycloak patterns.

Cons:

- still leaves the core runtime question open:
  - Docker socket,
  - remote sandbox service,
  - or unsafe process-style execution;
- easy for operators to over-assume multi-user/security properties that are not actually there.

Assessment:

- viable only if the human approval explicitly accepts single-user semantics and a reduced scope.

### Option C: Reframe to OpenHands Cloud / Enterprise evaluation

Description:

- if the real requirement is multi-user K3s-native OpenHands with Keycloak/RBAC-grade semantics, evaluate the licensed Kubernetes path instead of forcing the OSS Local GUI into that role.

Pros:

- aligns with upstream product boundaries;
- matches the fact that Cloud/Enterprise is where upstream places K8s self-hosting and multi-user features.

Cons:

- licensing / procurement / governance overhead;
- distinct repo and deployment path from the current OSS service.

Assessment:

- this is the only option reviewed here that naturally matches the original request's implied product expectations.

## Recommendation

Recommendation: **do not approve implementation of `TRA-215` in its current implied OSS shape**.

Require human approval of exactly one of these refined scopes:

1. **OSS Single-User Experiment**
   - K3s-hosted Local GUI style service
   - ingress-level auth only
   - no assumed app-native multi-user/RBAC
   - no shared Postgres requirement unless separately proven
   - explicit runtime decision required before any templates are written

2. **Licensed K8s Path Evaluation**
   - evaluate OpenHands Cloud / Enterprise self-hosted path
   - derive Keycloak and database requirements from that product's actual chart/docs

## Required Approval Questions

Before implementation, a human should answer:

1. Is the target actually **single-user OSS OpenHands**, or is the desired product shape effectively **Cloud/Enterprise-style multi-user OpenHands**?
2. If OSS is still desired, is ingress-only Keycloak gating acceptable even though app-native multi-user/RBAC is not established from the sources reviewed?
3. If OSS is still desired, which runtime model is approved?
   - Docker socket on K3s node(s)
   - new remote sandbox service
   - process/local execution
4. Is the shared Postgres requirement still mandatory, despite no current evidence that OSS OpenHands needs it?

## Dependencies Confirmed For Future Work

These remain relevant prerequisites for any K3s-side follow-up:

1. `TRA-119` Program: K3s cluster templates promotion and realization
2. `TRA-166` K3s research gate baseline
3. `TRA-191` Traefik Gateway baseline
4. `TRA-192` cert-manager baseline
5. `TRA-210` to `TRA-214` Keycloak helper set

But they are **not sufficient** by themselves to justify implementation, because the main blocker is product-shape mismatch, not only missing infrastructure.

## Sources

### Repo sources

- `stacks/llms/agents.yml`
- `clusters/llms/agents/beeai/README.md`
- `clusters/llms/agents/beeai/beeai.env.template`
- `clusters/llms/agents/beeai/values.yaml.template`
- `cluster-utils/src/cluster_utils/commands/keycloak.py`
- `cluster-utils/src/cluster_utils/commands/db.py`
- `reports/2026-02-25-tra-125-openhands-platform-fit-research.md`
- `reports/2026-03-03-tra-193-beeai-external-oidc-keycloak.md`
- `reports/2026-03-02-open-webui-db-user-naming-proposal.md`
- `reports/2026-02-26-tra-166-k3s-template-research-gate-baseline.md`
- `reports/2026-02-22-k3s-traefik-port-remap-for-443-ownership.md`

### Upstream sources

- OpenHands core repo README:
  - https://github.com/OpenHands/OpenHands
- OpenHands Docker sandbox docs:
  - https://docs.openhands.dev/openhands/usage/sandboxes/docker
- OpenHands runtime architecture docs:
  - https://docs.openhands.dev/openhands/usage/architecture/runtime
- OpenHands remote sandbox docs:
  - https://docs.openhands.dev/openhands/usage/sandboxes/remote
- OpenHands sandbox overview:
  - https://docs.openhands.dev/openhands/usage/sandboxes/overview
- OpenHands Cloud self-hosted repo:
  - https://github.com/All-Hands-AI/OpenHands-Cloud
- GitHub org / GHCR namespace migration notice:
  - https://github.com/OpenHands/OpenHands/issues/11376
