#!/bin/sh
set -eu

HERMES_HOME="${HERMES_HOME:-/var/lib/hermes}"
BASE_CONFIG_PATH="/etc/hermes/config.base.yaml"
TARGET_CONFIG_PATH="${HERMES_HOME}/config.yaml"

export TELEGRAM_BOT_TOKEN="$(cat /run/secrets/hermes_telegram_bot_token)"

mkdir -p "${HERMES_HOME}"

if [ -f "${BASE_CONFIG_PATH}" ]; then
  if [ "${HERMES_CONFIG_FORCE_REFRESH:-0}" = "1" ] || [ ! -f "${TARGET_CONFIG_PATH}" ]; then
    cp "${BASE_CONFIG_PATH}" "${TARGET_CONFIG_PATH}"
  fi
fi

if [ ! -d /opt/hermes-src/.git ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends git ca-certificates
  rm -rf /var/lib/apt/lists/*

  git clone --recurse-submodules https://github.com/NousResearch/hermes-agent.git /opt/hermes-src
fi

if [ ! -x /opt/hermes/bin/hermes ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends git ca-certificates
  rm -rf /var/lib/apt/lists/*

  python -m venv /opt/hermes
  /opt/hermes/bin/pip install --no-cache-dir --upgrade pip setuptools wheel
  /opt/hermes/bin/pip install --no-cache-dir -e "/opt/hermes-src[messaging,cron]"
  /opt/hermes/bin/pip install --no-cache-dir -e /opt/hermes-src/mini-swe-agent
fi

cd /opt/hermes-src
exec /opt/hermes/bin/python gateway/run.py
