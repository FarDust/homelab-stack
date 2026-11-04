#!/bin/bash
set -euo pipefail
export POSTGRES_PASSWORD
POSTGRES_PASSWORD="$(cat /run/secrets/marquez_postgres_password)"
exec /usr/src/app/entrypoint.sh
