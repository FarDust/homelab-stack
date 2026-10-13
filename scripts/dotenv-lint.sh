#!/usr/bin/env bash
# Run dotenv-linter without building anything: a dotenv-linter binary on PATH,
# else the pinned prebuilt image. Fails explicitly when neither exists.
# As decided in docs/adr/pre_commit_dotenv_linter_prebuilt_adr.md
set -euo pipefail

IMAGE="${DOTENV_LINTER_IMAGE:-dotenv-linter-prebuilt:v4.0.0}"

if command -v dotenv-linter >/dev/null 2>&1; then
  exec dotenv-linter "$@"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "dotenv-lint: neither dotenv-linter nor docker is available" >&2
  exit 2
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "dotenv-lint: image $IMAGE is not present on this host." >&2
  echo "dotenv-lint: build it once on frost-fang under the build lock (docker build -t $IMAGE https://github.com/dotenv-linter/dotenv-linter.git#v4.0.0) and load it here with docker save | docker load." >&2
  exit 2
fi

exec docker run --rm --network none --read-only --cap-drop ALL   -v "$PWD":/work:ro -w /work "$IMAGE" "$@"
