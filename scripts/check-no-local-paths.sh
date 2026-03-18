#!/usr/bin/env bash
# Reject staged content that contains local/host paths.

set -e
failed=0
while IFS= read -r -d '' path; do
  [[ "$path" == "scripts/check-no-local-paths.sh" ]] && continue
  if git show ":$path" 2>/dev/null | grep -qE '/home/[^/]*/|/root/[^.]|/root$|/Users/[^/]*/|C:\\Users\\[^\\]*\\'; then
    echo "$path: contains blocked host path pattern"
    failed=1
  fi
done < <(git diff --cached --name-only -z 2>/dev/null || true)
[ "$failed" -eq 0 ]
