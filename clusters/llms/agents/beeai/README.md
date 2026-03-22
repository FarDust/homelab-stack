# BeeAI Kubernetes Prerequisites (Template-Only)

This folder defines commit-safe BeeAI prerequisites for an Agent Stack reintroduction.
No Swarm changes are performed here.

## Files

- `beeai.env.template`: local variable realization contract.
- `namespace.yaml.template`: BeeAI namespace template.
- `serviceaccount.yaml.template`: dedicated service account template.
- `values.yaml.template`: pinned BeeAI chart values with LiteLLM + shared Postgres contract.
- `httproute-ui.yaml.template`: Gateway API route for BeeAI UI through Traefik (`websecure` listener).
- `httproute-api.yaml.template`: Gateway API route for BeeAI API through Traefik (`websecure` listener).

## Render (local only)

```bash
cp clusters/llms/agents/beeai/beeai.env.template clusters/llms/agents/beeai/beeai.env
# edit clusters/llms/agents/beeai/beeai.env
# (BEEAI_LITELLM_API_KEY should resolve from secrets/beeai/litellm_api_key)

set -a
source .env
source clusters/llms/agents/beeai/beeai.env
set +a

envsubst < clusters/llms/agents/beeai/namespace.yaml.template > clusters/llms/agents/beeai/namespace.yaml
envsubst < clusters/llms/agents/beeai/serviceaccount.yaml.template > clusters/llms/agents/beeai/serviceaccount.yaml
envsubst < clusters/llms/agents/beeai/values.yaml.template > clusters/llms/agents/beeai/values.yaml
envsubst < clusters/llms/agents/beeai/httproute-ui.yaml.template > clusters/llms/agents/beeai/httproute-ui.yaml
envsubst < clusters/llms/agents/beeai/httproute-api.yaml.template > clusters/llms/agents/beeai/httproute-api.yaml
```

Rendered files are gitignored.

## Apply Prerequisites

```bash
kubectl apply -f clusters/llms/agents/beeai/namespace.yaml
kubectl apply -f clusters/llms/agents/beeai/serviceaccount.yaml
kubectl apply -f clusters/llms/agents/beeai/httproute-ui.yaml
kubectl apply -f clusters/llms/agents/beeai/httproute-api.yaml
```

## Install / Upgrade BeeAI (pinned chart)

```bash
set -a
source .env
source clusters/llms/agents/beeai/beeai.env
set +a

helm upgrade --install "${BEEAI_RELEASE_NAME}" \
  -n "${BEEAI_NAMESPACE}" \
  -f clusters/llms/agents/beeai/values.yaml \
  --version "${BEEAI_CHART_VERSION}" \
  oci://ghcr.io/i-am-bee/agentstack/chart/agentstack

# Official BeeAI API bootstrap (model provider + defaults)
kubectl -n "${BEEAI_NAMESPACE}" port-forward svc/beeai-platform-svc 18333:8333
# in another shell:
ADMIN_PASSWORD="$(kubectl -n "${BEEAI_NAMESPACE}" get secret beeai-platform-secret -o jsonpath='{.data.adminPassword}' | base64 -d)"
BEEAI_API_KEY="$(cat secrets/beeai/litellm_api_key | tr -d '\n')"
curl -sS -u "admin:${ADMIN_PASSWORD}" \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:18333/api/v1/model_providers \
  -d "{\"name\":\"litellm\",\"type\":\"openai\",\"base_url\":\"https://litellm.${LOCAL_DOMAIN}/v1\",\"api_key\":\"${BEEAI_API_KEY}\"}" || true
curl -sS -u "admin:${ADMIN_PASSWORD}" \
  -H 'Content-Type: application/json' \
  -X PUT http://127.0.0.1:18333/api/v1/configurations/system \
  -d '{"default_llm_model":"openai:n8n-chat","default_embedding_model":"openai:text-embedding-3-small"}'
# set Chat agent runtime model explicitly
CHAT_PROVIDER_ID="$(curl -sS -u "admin:${ADMIN_PASSWORD}" http://127.0.0.1:18333/api/v1/providers | jq -r '.items[] | select(.agent_card.name=="Chat") | .id' | head -n1)"
curl -sS -u "admin:${ADMIN_PASSWORD}" \
  -H 'Content-Type: application/json' \
  -X PUT "http://127.0.0.1:18333/api/v1/providers/${CHAT_PROVIDER_ID}/variables" \
  -d '{"variables":{"CHAT_MODEL":"openai:n8n-chat"}}'
```

## Validation Checklist

```bash
kubectl -n "${BEEAI_NAMESPACE}" get pods,svc
kubectl -n "${BEEAI_NAMESPACE}" get httproute
kubectl -n "${BEEAI_NAMESPACE}" logs deployment/beeai-platform --tail=200
kubectl -n "${BEEAI_NAMESPACE}" get sa "${BEEAI_SERVICE_ACCOUNT_NAME}"
```

## Notes

- `BEEAI_POSTGRES_*` values are prerequisites and must map to a shared existing Postgres DB/user pair.
- Keep versions pinned (`BEEAI_CHART_VERSION`, `BEEAI_IMAGE_TAG`, `BEEAI_REGISTRY_VERSION`).
- Do not commit rendered files or secret realizations.
