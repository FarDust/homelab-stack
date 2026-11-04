path "auth/jwt/role/*" {
  capabilities = ["create", "update"]
}

path "sys/policies/acl/*" {
  capabilities = ["create", "update"]
}

path "secret/data/services/*" {
  capabilities = ["create", "update"]
}

path "secret/data/services/workspace-backups/*" {
  capabilities = ["create", "update", "read"]
}

path "secret/data/services/accounting-statements-agent/litellm" {
  capabilities = ["create", "update", "read"]
}

path "secret/data/services/graphify-headless/litellm" {
  capabilities = ["create", "update", "read"]
}

path "secret/data/services/pr-agent/litellm" {
  capabilities = ["create", "update", "read"]
}

path "secret/data/services/postgres/*" {
  capabilities = ["create", "update", "read"]
}

path "secret/data/services/redis/*" {
  capabilities = ["create", "update", "read"]
}

path "secret/data/services/openchamber-stt/litellm" {
  capabilities = ["create", "update", "read"]
}

path "secret/data/services/minecraft-chat/litellm" {
  capabilities = ["create", "update", "read"]
}
