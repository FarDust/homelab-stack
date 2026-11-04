#!/bin/sh
set -eu

if ! dpkg -s postgresql-17-pgvector >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends postgresql-17-pgvector
  rm -rf /var/lib/apt/lists/*
fi

/usr/local/bin/postgres-cert-watch.sh --no-reload

upstream_pid=
watcher_pid=

terminate_children() {
  trap - TERM INT
  if [ -n "$watcher_pid" ]; then
    kill -TERM "$watcher_pid" 2>/dev/null || :
  fi
  if [ -n "$upstream_pid" ]; then
    kill -TERM "$upstream_pid" 2>/dev/null || :
  fi
  if [ -n "$watcher_pid" ]; then
    wait "$watcher_pid" 2>/dev/null || :
  fi
  if [ -n "$upstream_pid" ]; then
    wait "$upstream_pid" 2>/dev/null || :
  fi
  exit 143
}

trap terminate_children TERM INT

if [ -x /scripts/docker-entrypoint.sh ]; then
  /bin/bash /scripts/docker-entrypoint.sh "$@" &
  upstream_pid=$!
elif [ -x /usr/local/bin/docker-entrypoint.sh ]; then
  /usr/local/bin/docker-entrypoint.sh "$@" &
  upstream_pid=$!
else
  echo "No known upstream entrypoint found" >&2
  exit 127
fi

/usr/local/bin/postgres-cert-watch.sh --watch &
watcher_pid=$!

while :; do
  if ! kill -0 "$upstream_pid" 2>/dev/null; then
    if wait "$upstream_pid"; then
      upstream_status=0
    else
      upstream_status=$?
    fi
    kill -TERM "$watcher_pid" 2>/dev/null || :
    wait "$watcher_pid" 2>/dev/null || :
    exit "$upstream_status"
  fi

  if ! kill -0 "$watcher_pid" 2>/dev/null; then
    wait "$watcher_pid" 2>/dev/null || :
    kill -TERM "$upstream_pid" 2>/dev/null || :
    wait "$upstream_pid" 2>/dev/null || :
    exit 1
  fi

  sleep 1
done
