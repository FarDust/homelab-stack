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

## Secret source recommendation (configuration management)

Status: recommended, not yet implemented. The contract above names every variable and the file pattern behind each secret; this
section decides where the secret values should come from, so that the plaintext `secrets/` directory stops being the system of record.

### Context

Today one git-ignored plaintext tree feeds two routes: Swarm `secrets:` entries and `export NAME=$(cat secrets/...)` lines. Whoever can
read the deploy host's checkout reads every secret, there is no per-reader authorization, no audit trail, and rotation is a file edit plus
a `CONFIG_VERSION` bump. The cluster already runs OpenBao, and a Trust Agent that creates service identities and stores service secrets
at fixed OpenBao KV paths through typed, create-once, metadata-only operations, with exact per-secret consumer roles. The decision is
therefore not "which store to adopt" but "which existing store becomes the source for the contract's secret variables".

Candidates were measured against the library rule (more than 1000 GitHub stars, checked 2026-11-04 with `gh api`):

| Candidate | Stars | Fit |
| --- | --- | --- |
| SOPS | 23613 | Encrypted files in Git; needs a decryption key on every deploy host |
| age (SOPS key backend) | 24202 | Key format only, not a store |
| Infisical | 30270 | Full secrets platform; a new stateful service (database, cache, encryption keys) |
| OpenBao | 8867 | Already deployed; KV, policies, JWT/OIDC roles, audit devices, response wrapping |

### Decision

Make OpenBao, written through the Trust Agent, the single source of truth for the values of every `kind: secret-file` variable, and keep
`config/env-contract.yaml` as the schema that says which variable maps to which secret. Keep the shell-script `.env` layering and the Swarm
`secrets:` mechanism unchanged for consumers; only the origin of the bytes under `secrets/` changes. SOPS with age is used for exactly one
narrow purpose, if at all: a small encrypted bundle for the tier-0 bootstrap secrets (below), stored outside this public repository.
Infisical is not adopted.

Contract additions (all checked statically, still names and patterns only):

- `secret_path`: the KV path pattern for each secret-file variable, derived from the existing convention `<service>/<name>`, validated by
  `check` the same way `secret_file` is.
- `tier`: `0` for secrets the secret store itself needs in order to start and be reached (the OpenBao storage and unseal material, the
  identity provider client that the Trust Agent authenticates through, the Trust Agent's own credentials), `1` for everything else.
  `check` fails if a tier-1 variable is listed as a dependency of a tier-0 service.

### The bootstrap problem (chicken and egg)

Any store needs something outside itself to start, and SOPS, Infisical and OpenBao all have the problem; they only differ in what that
something is.

- SOPS: the age private key must exist on every host that deploys. It is a plaintext secret on disk, the same tier as today's `secrets/`
  tree, and it protects everything. SOPS therefore moves the problem to one file, which is an improvement for review and history but not
  for custody, and in a public repository it publishes ciphertext permanently, so a later key leak decrypts all history.
- Infisical: needs its own database, encryption key and auth secret before it can serve, and it runs on the cluster it configures, so a
  cold start of the whole cluster cannot depend on it.
- OpenBao: needs unseal material and a storage backend. This is the smallest and best-understood bootstrap surface, and it is already
  paid for.

Resolution: define a tier-0 set and keep it deliberately small and boring.

1. Tier-0 secrets stay as files read at deploy time (as today), but are limited to the store's own storage credential, the seal
   configuration and the Trust Agent bootstrap credential. Their names are listed in the contract with `tier: 0`.
2. Unseal shares (or a recovery key if an auto-unseal seal is configured, for example a cloud KMS key or a transit seal) are held outside the
   cluster and outside this repository: split among custodians in the operator's password manager and an offline copy. An agent never holds a
   full threshold.
3. Cold-start order is documented and tested: tier-0 files, then the store and its dependencies, unseal, then everything else materialises.
   A restore drill that starts from nothing but the offline tier-0 material is the acceptance test.
4. Tier-1 secrets are written once into OpenBao by the Trust Agent (create-once, fingerprint verified), after which the plaintext file is
   replaced by a materialised copy (below).

### Materialisation, preserving the existing contract

A host-side step before `docker stack deploy` (a `cluster-utils` command, not a new service) reads each tier-1 secret from OpenBao with a
deploy-scoped role that can read only the paths the contract lists for the stacks being deployed, and writes them to a tmpfs-backed
`secrets/` directory with owner-only permissions. Everything downstream is unchanged: `.env` still sources `cat secrets/<dir>/<file>`,
Swarm `secrets:` still point at `file:`, and `env_contract.py check-live` still compares names only. Consequences of the materialiser:
plaintext exists only in memory-backed storage for the duration of a deploy, the OpenBao audit log records which role read which path, and a
failed fetch aborts the deploy with the variable name instead of rendering an empty value.

### Alternatives considered for this decision

- SOPS plus age as the primary store: rejected as the source of truth because of the single on-host key, permanent public ciphertext, no
  per-reader authorization, and no audit; retained only as an optional encrypted container for the tier-0 bundle, outside the repository.
- Infisical as the primary store: rejected for a second stateful secrets platform that duplicates policies, identities and audit already
  provided by OpenBao and the Trust Agent, and that cannot serve a cold start of the cluster it configures.
- Staying on plaintext files with only the contract: rejected as the end state; acceptable as stage 0.
- Cloud secret manager as primary: viable, but adds an external dependency to every deploy and duplicates the access model; remains an
  option as the auto-unseal key source only.

### Consequences

- Rotation becomes a Trust Agent operation followed by a deploy, and the contract tells reviewers which variables and stacks are affected.
- The plaintext tree shrinks to the tier-0 files. Backups of the deploy host stop being a copy of every secret.
- The Trust Agent and OpenBao become deploy-time dependencies for tier-1 stacks; an outage blocks deploys (not running services), which is
  the intended failure mode and is reported as an explicit error.
- Variables delivered as environment values rather than Swarm secrets stay visible in service specs; the migration moves them to `_FILE`
  consumption where the image supports it, tracked per variable in the contract.
- New work: contract fields, the materialiser, an import tool that wraps the Trust Agent operations, and the cold-start drill.

### Staged migration

1. Contract only (done). Add `secret_path` and `tier` fields and validate them; no behaviour change.
2. Inventory and classify: assign tiers, find tier-1 secrets that the store transitively needs and demote them to tier 0 or break the cycle.
3. Import: the Trust Agent creates each tier-1 secret in OpenBao from the existing file, create-once; a fingerprint comparison proves the
   stored value equals the file value without printing it. Files stay in place.
4. Shadow read: the materialiser runs in dry-run on deploy, fetches each value, compares fingerprints with the file, and reports mismatches
   by name. Run for a full deploy cycle of every stack.
5. Cut over per stack, lowest blast radius first: deploy from the materialised tmpfs tree, confirm the service is healthy and the secret
   was read by the expected role in the audit log, then delete that stack's plaintext files.
6. Tier-0 hardening: move unseal custody offline, optionally configure auto-unseal, and run the cold-start drill from offline material.
7. Retire: remove the remaining plaintext tier-1 files, bump the contract version, and record the rotation procedure.

Each stage is reversible until step 7 because the original files remain the fallback.

### Verification

- Stage 1: `scripts/env_contract.py check` fails on a secret variable without `secret_path` or with an invalid `tier`, covered by new
  tests in `tests/test_env_contract.py` (missing field, tier-1 dependency of a tier-0 service).
- Stages 3 and 4: the import and shadow-read report only names and match/mismatch results; a test with a sentinel value proves no value
  is printed. A forced mismatch and a forced OpenBao outage must each abort the dry run with a named, nonzero failure.
- Stage 5: after each cutover, the service health check passes, the audit log shows a read by the deploy role on the expected path only,
  and a read of an unlisted path is denied.
- Stage 6: the cold-start drill brings up the store from offline tier-0 material alone, then deploys one tier-1 stack end to end.
- Success for the whole decision is observable: no tier-1 plaintext file remains on the deploy host, and every deploy secret read is
  attributable in the audit log.
