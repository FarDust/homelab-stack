# Pre-commit dotenv-linter without image builds

Date: 2026-10-13

## Context

Commits on fardustdev (a 2-CPU Swarm manager) sometimes built a Docker image. The cause is the `dotenv-linter/dotenv-linter` hook in `.pre-commit-config.yaml`: its upstream definition uses `language: docker`, so pre-commit builds the upstream Dockerfile (a Rust compile of dotenv-linter) whenever its environment is missing or invalidated. The local image `pre-commit-c1aed8c8...` was built at 07:46 UTC on 2026-10-13, in the commit path. Pre-commit prepares the environments of all configured hooks on each run, even when no `.env*` file is staged.

## Decision

Replace the upstream hook with a local hook `dotenv-linter` that runs `scripts/dotenv-lint.sh`. The script uses a `dotenv-linter` binary on PATH when present and otherwise `docker run` of the already present image `dotenv-linter-prebuilt:v4.0.0` (dotenv-linter 4.0.0, the version of the removed `rev`) with no network, a read-only root and the working tree mounted read-only. If neither exists it exits 2 with the recovery step: build the image once on frost-fang under the build lock and move it with `docker save | docker load`. Arguments, `files` and `exclude` are unchanged. GitGuardian (`ggshield-quota-guard`) and Gitleaks stay enabled and untouched; they already run as `language: system`.

## Alternatives

- Pin an image in a registry: needs a pull on the manager and a registry we publish to; deferred.
- Move the check to CI on frost-fang: a valid addition, but the local gate is useful before a commit and costs one container start.
- Run only on changed files: the hook already filters on `.env*`; the cost was the environment build, not the lint.
- Drop the check: rejected, it guards the env files.

## Consequences

- No image build at commit time; a lint run costs one `docker run` of a 4 MB image.
- The prebuilt image is host-local; losing it makes the hook fail loudly (exit 2), never pass silently.
- The stale `pre-commit-c1aed8c8...` image and its pre-commit cache entry can be removed later (not done here).

## Verification

`scripts/dotenv-lint.sh check ... .env.example` printed `No problems found`; a file containing `BAD LINE` produced two findings and exit 1, so the gate fails on bad input. The config diff touches only the dotenv-linter entry.
