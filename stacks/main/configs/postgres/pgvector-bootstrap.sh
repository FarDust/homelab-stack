#!/bin/sh
set -eu

if ! dpkg -s postgresql-17-pgvector >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends postgresql-17-pgvector
  rm -rf /var/lib/apt/lists/*
fi

if [ -x /scripts/docker-entrypoint.sh ]; then
  exec /bin/bash /scripts/docker-entrypoint.sh "$@"
fi

if [ -x /usr/local/bin/docker-entrypoint.sh ]; then
  exec /usr/local/bin/docker-entrypoint.sh "$@"
fi

echo "No known upstream entrypoint found" >&2
exit 127
