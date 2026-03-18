#!/usr/bin/env bash
# Reject staged content that contains local/host paths.
# Whitelist: container paths in volume mounts (e.g. volume_name:/home/user/...).

BLOCKED='/home/[^/]*/|/root/[^.]|/root$|/Users/[^/]*/|C:\\Users\\[^\\]*\\'
# Lines that may contain /home/ or /root/ but are safe (compose volume mount targets)
WHITELIST='^\s*-\s*[^:]+:\s*/home/|^\s*-\s*[^:]+:\s*/root'

set -e
failed=0
while IFS= read -r -d '' path; do
  [[ "$path" == "scripts/check-no-local-paths.sh" ]] && continue
  content=$(git show ":$path" 2>/dev/null) || continue
  if echo "$content" | grep -vE "$WHITELIST" | grep -qE "$BLOCKED"; then
    echo "$path: contains blocked host path pattern"
    failed=1
  fi
done < <(git diff --cached --name-only -z 2>/dev/null || true)
[ "$failed" -eq 0 ]
