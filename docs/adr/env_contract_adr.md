# Environment-variable contract

## Context

The stacks under `stacks/*/*.yml` interpolate about 350 variables (`${VAR}`, `${VAR:-default}`, `${VAR?message}`, bare `$VAR`).
Their values come from a live `.env` that is not a dotenv file but a shell script sourced from the compose root, in three layers:

1. literals: `export NAME=value`;
2. secret reads: `export NAME=$(cat secrets/<dir>/<file> | tr -d '\n')`, pulling plaintext from the git-ignored secrets directory at
   the moment the file is sourced (the same files also feed Swarm `secrets:` entries);
3. computed values: `export NAME=$(command)`.

Nothing recorded which variables exist, who owns them, which stacks share them, which are required, or which secret file backs each
secret. `.env.example` was hand-written and drifted; undefined variables silently rendered empty (five `${VAR?}` variables and
twenty bare `${VAR}` variables had no definition in the live `.env`). The repository is public, so any record must hold names,
kinds and file-name patterns only.

How `.env` reaches `docker stack deploy` (read from `cluster-utils/src/cluster_utils`): `deploy` first calls `require_dotenv()`, which
loads `.env` with `python-dotenv` and, because the file contains `export ` or `$(`, re-sources it in `bash -lc 'set -a; source .env; env -0'`
and copies the result into `os.environ`. The following `bash -c 'cd <dir> && source .env && docker stack deploy ...'` inherits that
environment. Therefore the 15 lines written without `export` (for example `EPHEMERAL_REBALANCE_*`, `RCLONE_CONTROLLER_IMAGE`,
`KEYCLOAK_IMAGE`) do reach `docker stack deploy` when it is started through cluster-utils, because `set -a` exports every assignment.
They do not reach it through a plain `source .env && docker stack deploy` typed by hand, nor through any other child process of
a shell that merely sourced the file. The contract records them with `exported: false`, and `check-live` fails if the live file
changes that.

## Decision

Keep one typed contract, `config/env-contract.yaml`, validated with pydantic models and parsed with PyYAML, and a Typer tool,
`scripts/env_contract.py` (uv script header, Rich output, pydantic-settings for paths):

- Each variable declares `name`, `kind` (`literal`, `secret-file`, `computed`), `owner` stack, `used_by` stacks (stack id is
  `<directory>/<file stem>` of the stack file), `required` or an explicit `default`, `description`, an optional `example` placeholder,
  and for secrets only `secret_file`, the name pattern under `secrets/`. Secrets accept no example and only the empty default.
  `external_consumers` marks variables that stacks do not interpolate (cluster-utils, scripts); `exported` and `in_example` record the
  non-exported lines and names that must never appear in a copyable example (`PATH`).
- `scan` walks the parsed YAML scalars (comments are ignored, `$$` escapes honoured, nested operands followed).
- `check` fails when a used variable is missing from the contract, a listed variable is unused (unless `external_consumers`), a
  `used_by` set differs from the scan, a stack requires a variable the contract does not mark required, a variable is used without
  default and without a decision, or `.env.example` and the contract disagree on names.
- `generate-example` renders `.env.example` from the contract, so the example cannot drift.
- `check-live PATH` compares only names, the `export` flag and the kind (secret read, computed, literal) of a live `.env`. It never
  evaluates the file and prints no value; the right-hand side is inspected only for its prefix.
- A pre-commit hook `env-contract` runs `check`; the pre-commit CI workflow installs uv so the same hook runs there.

The contract was seeded from the scan and the live `.env` names, so owners (the first stack, preferring `main/`), descriptions without
an `.env.example` comment, and conflicting defaults (three variables use different defaults in different stacks; the first sorted
default was kept) are starting points for review. Resolved gaps: the five required variables with no live definition are `required: true`
(`check-live` reports them as errors, which is the true state); the twenty bare variables with no definition and no default carry
`default: ""`, which documents the current behaviour (compose renders them empty) without changing a deployment.

Known defect recorded, not fixed here: `stacks/llms/mcp.yml` writes `$PATH` where `$$PATH` is meant, so compose interpolates the
deployer's `PATH`. The contract carries `PATH` with `in_example: false` so the check passes while the defect stays visible.

## Alternatives

- SOPS with age, encrypted secrets committed to the repository: gives review and history for secrets, but the repository is
  public, and bootstrapping has a chicken-and-egg problem: the age private key (and the means to decrypt on a fresh host) must exist
  before any encrypted file is usable, and that key would itself live outside the repository in the same plaintext tier as today's
  `secrets/` directory. It also does not describe the shell-script layering, which stays.
- Self-hosted Infisical: a UI and API for secrets, but it runs on the cluster it would configure (it needs its own database and
  keys before it can serve anyone), and adds a service to operate for what is mainly a naming and ownership problem.
- OpenBao with consul-template: the target direction already recorded for secrets (a central KV fed by the trust agent). OpenBao is
  bootstrapped from the secrets directory, so the same chicken-and-egg applies, and a template layer would still need a contract of names
  to render. This contract is a prerequisite and does not exclude it.
- direnv: loads a per-directory environment on a developer shell, which is not how the Swarm deploy runs (`cluster-utils` sources `.env`),
  and it still executes the shell script without validating anything.
- Parsing `.env` with a dotenv library for the live check: rejected because the file is shell code (`$(cat ...)`), and a parser
  would read, keep or mis-evaluate values; a name-only line match is enough and keeps values out of memory and output.

## Consequences

- Adding, renaming or removing an interpolated variable requires a contract edit and `generate-example` in the same commit.
- `.env.example` is generated; hand edits are overwritten.
- Secret values never enter the repository; only the secret file name pattern does. The 5 required variables absent from the live
  `.env` are a recorded deployment gap to fill, not a check failure for commits (`check` is static; `check-live` is run on the host).
- Variables that only tools read (about 70 names in the live `.env` that no stack interpolates) are listed with `external_consumers`
  taken from a repository search; `unreferenced-in-tracked-files` marks cleanup candidates.
- Descriptions are seeded; improving them is incremental work.

## Verification

- `uv run --script scripts/env_contract.py check` exits 0 on this repository.
- `uv run --no-project --with pytest --with pyyaml pytest tests/test_env_contract.py` covers scanning (defaults, nested operands, escapes,
  comments), missing, unused and shared-mismatch variables, stack-required versus contract, example drift, malformed contracts,
  unterminated interpolation, and that `check-live` prints no value from a file holding a sentinel.
- On the host: `scripts/env_contract.py check-live .env` lists name-level differences without values.
