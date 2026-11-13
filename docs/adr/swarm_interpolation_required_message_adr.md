# Required-variable messages in Swarm stack files carry no hyphen

Status: accepted, 2026-11-13.

## Context

`stacks/main/traefik.yml` read its private deployment files through
`${HOMELAB_PRIVATE_DIR:?... (docs/homelab-private.md)}`. On 2026-11-13 00:04 UTC a single-service deploy of Prometheus failed before any
change because the ingress probe targets config pointed at `<stack dir>/private.md)/stacks/main/configs/prometheus/...`.

`docker stack deploy` and `docker stack config` (Docker CLI 29.9.3) interpolate with the CLI's own template code, not with the
Compose implementation behind `docker compose config`. That code looks for the default operators `:-` and `-` before the required
operators `:?` and `?`. A hyphen anywhere in the message is therefore taken as the `-` operator: the text before it becomes an
unknown variable name and the text after it becomes the value. This happens whether or not the variable is set, so the expression
also stops failing closed when the variable is missing.

Reproduction with `PDIR=/opt/priv`, rendered by `docker stack config`:

| Expression | Result |
| --- | --- |
| `${PDIR:?PDIR must be set (docs/homelab-private.md)}/x.yaml` | `<dir>/private.md)/x.yaml`, also when `PDIR` is unset |
| `${PDIR:?a-b}/x.yaml` | `<dir>/b/x.yaml` |
| `${PDIR:?PDIR must be set, see docs}/x.yaml` | `/opt/priv/x.yaml`; unset: "required variable PDIR is missing a value" |
| `${PDIR?err}/x.yaml` | `/opt/priv/x.yaml` |

CI did not catch it because the compose validation renders with `docker compose config`, which parses the same expression correctly.
The six affected references (five Grafana dashboards and the Prometheus ingress probe targets) date from the move to the private
deployment directory on 2026-11-04; the running Prometheus and Grafana services still carry configs created before that change.

## Decision

Messages of `${VAR:?message}` and `${VAR?message}` in compose files under `stacks/` contain no hyphen. The six `HOMELAB_PRIVATE_DIR`
references in `stacks/main/traefik.yml` share one hyphen-free message. `tests/test_stack_interpolation_messages.py` scans every
compose file under `stacks/` and fails on a hyphen in such a message; it runs in the pre-commit workflow test step.
The scan covers `stacks/<folder>/<file>.yml`, the same set the compose validation workflow renders and the only files
`docker stack deploy` interpolates; files under `configs/` are passed to containers verbatim and are out of scope.

## Alternatives

- Short form `${HOMELAB_PRIVATE_DIR?err}` as in `main/storage` and `productivity/finance`: also correct, but the message that names
  the variable's purpose is lost. Both forms stay allowed.
- Rendering in `cluster-utils` with the Compose implementation before `docker stack deploy`: changes the deploy path of every stack
  and its rendered output (resolved paths, normalized keys); out of proportion to a wording rule.
- Adding a `docker stack config` render to CI: needs a Swarm-capable Docker in the runner for every compose file. The static test
  covers the known quirk at no runtime cost; a render check can be added later for other differences between the two parsers.

## Consequences

- `deploy service prometheus` and `deploy service grafana` resolve the private files again, and a missing `HOMELAB_PRIVATE_DIR`
  fails the render with the message instead of producing a wrong path.
- Authors keep hyphenated file names out of these messages and point to documentation in words.

## Verification

- `uv run --no-project --with pytest --with pyyaml pytest -q tests/test_stack_interpolation_messages.py`.
- `scripts/tests/test-grafana-config-version.sh`.
- `docker stack config` on the extracted Prometheus and Grafana services resolves every private file to an existing path under
  `HOMELAB_PRIVATE_DIR`.
