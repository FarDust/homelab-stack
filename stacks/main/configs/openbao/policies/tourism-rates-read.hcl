path "secret/data/tourism-rates/*" {
  capabilities = ["read"]
}

path "secret/metadata/tourism-rates/*" {
  capabilities = ["read", "list"]
}
