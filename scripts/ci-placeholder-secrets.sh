#!/usr/bin/env bash
# Create placeholder files for every secret path that .env.example reads, so CI can source it
# and render the stacks without real secrets. As decided in docs/adr/env_contract_adr.md
set -euo pipefail

example="${1:-.env.example}"
grep -o 'secrets/[A-Za-z0-9_./-]*' "$example" | sort -u | while read -r secret_file; do
  mkdir -p "$(dirname "$secret_file")"
  printf 'placeholder' > "$secret_file"
done
