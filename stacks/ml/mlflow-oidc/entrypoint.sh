#!/bin/sh
# Swarm-secret friendly entrypoint: for each NAME_FILE variable, export NAME with the file's contents.
set -eu
for name in OIDC_CLIENT_SECRET SECRET_KEY MLFLOW_BACKEND_STORE_URI OIDC_USERS_DB_URI; do
  eval "file=\${${name}_FILE:-}"
  if [ -n "$file" ]; then
    if [ ! -r "$file" ]; then
      echo "entrypoint: ${name}_FILE=$file is not readable" >&2
      exit 78
    fi
    value=$(cat "$file")
    export "$name=$value"
  fi
done
exec python -m mlflow "$@"
