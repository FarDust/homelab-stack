#!/bin/sh

# Ensure jq is installed (for Alpine-based images)
if ! command -v jq >/dev/null 2>&1; then
  echo "🔧 jq not found, installing..."
  if command -v apk >/dev/null 2>&1; then
    apk add --no-cache jq || { echo "❌ Failed to install jq"; exit 1; }
  else
    echo "🚫 No supported package manager found to install jq. Exiting." >&2
    exit 1
  fi
fi

: "${RCLONE_FIX_ENABLED:=false}"
: "${RCLONE_FIX_INTERVAL:=60}"

STATE_FILE="/state/docker-plugin.state"

if [ "$RCLONE_FIX_ENABLED" != "true" ]; then
  echo "🛑 Fixer disabled. Exiting."
  exit 0
fi

echo "⏱️ Running every $RCLONE_FIX_INTERVAL sec..."

while true; do
  if ! docker plugin inspect rclone >/dev/null 2>&1; then
    echo "❌ Plugin not found."
  elif ! docker plugin inspect rclone --format '{{.Enabled}}' | grep -q true; then
    echo "⚠️ rclone is disabled. Fixing..."
    TMP_FILE="$(mktemp /tmp/tmp.state.XXXXXX)"
    if jq 'map(.mounts = [])' "$STATE_FILE" > "$TMP_FILE"; then
      if cp "$TMP_FILE" "$STATE_FILE"; then
        echo "✅ State file updated."
      else
        echo "❌ Failed to overwrite state file (resource busy). Retrying in 10s..."
        sleep 10
        continue
      fi
    else
      echo "❌ jq failed to process state file."
      sleep 10
      continue
    fi
    docker plugin enable rclone && echo "✅ rclone re-enabled."
  else
    echo "🟢 rclone OK."
  fi
  sleep "$RCLONE_FIX_INTERVAL"
done
