#!/usr/bin/env bash
# Reject staged content that contains local/host paths.
# Whitelist: container paths in volume mounts; docs with backtick-wrapped paths (e.g. README).

BLOCKED='/home/[^/]*/|/root/[^.]|/root$|/Users/[^/]*/|C:\\Users\\[^\\]*\\'
# Safe: compose volume mount targets (name:/home/...); markdown list items with `.../home/...` or `.../root...`
WHITELIST='^\s*-\s*[^:]+:\s*/home/|^\s*-\s*[^:]+:\s*/root|^\s*-\s*`[^`]*/home/|^\s*-\s*`[^`]*/root'

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
