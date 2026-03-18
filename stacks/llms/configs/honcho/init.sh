#!/bin/sh
set -eu

mode="${1:-api}"

export DEBIAN_FRONTEND=noninteractive

if ! command -v git >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends git ca-certificates curl
  rm -rf /var/lib/apt/lists/*
fi

if [ ! -d /opt/honcho-src/.git ]; then
  git clone --depth 1 --branch v3.0.3 https://github.com/plastic-labs/honcho.git /opt/honcho-src
fi

db_password="$(tr -d '\n' </run/secrets/honcho_db_password)"
redis_password="$(tr -d '\n' </run/secrets/redis_password)"
redis_db="${HONCHO_REDIS_DB:-9}"

db_password_encoded="$(python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$db_password")"
redis_password_encoded="$(python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$redis_password")"

export DB_CONNECTION_URI="postgresql+psycopg://${DB_USER}:${db_password_encoded}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
export CACHE_URL="redis://:${redis_password_encoded}@redis:6379/${redis_db}?suppress=true"

cd /opt/honcho-src

if [ -d /opt/honcho-src/.venv ]; then
  rm -rf /opt/honcho-src/.venv
fi

pip install --no-cache-dir --upgrade pip uv
uv sync --frozen --no-group dev

if [ "$mode" = "api" ]; then
  uv run alembic upgrade head
  exec uv run fastapi run --host 0.0.0.0 --port 8000 src/main.py
fi

exec uv run python -m src.deriver
