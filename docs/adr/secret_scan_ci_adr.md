# ADR: Independent secret gates in Linux CI

Date: 2026-10-11. Status: implemented; hosted execution and independent approval pending.

## Context

The previous workflow skipped the API scanner. The approved replacement requires the
maintained quota guard when configured and an independent local scanner, while preserving ordinary
repository hooks. It must not depend on a production-node build or change deployment.

## Decision

Use one GitHub-hosted Ubuntu 24.04 job with a five-minute timeout, full Git history,
Python 3.12, uv 0.12.5, pre-commit 4.5.1 and Gitleaks 8.30.1. Actions are SHA-pinned;
the Gitleaks release archive is checksum-pinned. Cache uv dependencies and hook environments.
Retain applicable non-scanner hooks, the quota-boundary regression tests and tests that
execute the actual workflow step for absent/empty keys and a rejected configured key.

Gabriel's 2026-10-11 decision makes GitGuardian optional when Gitleaks runs. If the API
key is absent or empty, emit `::notice::GitGuardian API key not configured; Gitleaks is
the required gate` and exit zero without calling the API guard. Otherwise run
`uv run --python 3.12 --script scripts/secret_scan_guard.py ci`. A configured but rejected
key remains blocking, as do findings and other errors. Confirmed exhausted quota retains
the approved two-signal guard; this decision does not alter its implementation.

Run Gitleaks as a separate required step even when the API step fails. Neither step uses
continue-on-error. Missing or failed Gitleaks remains blocking. This supersedes the
earlier requirement that missing API authentication block CI.

When API scanning is desired, provision `GITGUARDIAN_API_KEY` through approved credential
custody. Its value is exposed only to the API step, not other steps or source files.
Fork PRs do not receive repository secrets and use the required local gate; do not use
pull_request_target to expose credentials to PR code.

## Local execution and review follow-up

The repository's `.python-version` remains 3.10.12 for existing consumers. Invoke the
guard explicitly with `uv run --python 3.12 --script` from its hook, shebang, examples
and subprocess tests, matching CI rather than inheriting an incompatible interpreter.

Each guard child process has a default 60-second timeout, configurable through the
positive, finite `GGSHIELD_COMMAND_TIMEOUT_SECONDS` setting. A scan timeout exits 124;
a quota lookup timeout cannot confirm exhaustion and preserves the original scan exit
128. Diagnostics identify the timed-out operation without replaying partial payloads.
The subprocess API owns cancellation; no retry or alternate scan path is introduced.

Install the official Gitleaks 8.30.1 prebuilt binary on the local PATH. The system hook
checks its reported version before the real staged scan and blocks missing, mismatched
or failed version queries. This retains the approved binary workflow rather than
compiling Go on pressured nodes. Version checking is not a substitute for verifying
the official archive checksum at installation. CI's checksum-pinned installer remains.

Checkout uses `persist-credentials: false`; no later step requires a stored checkout
token. Keep `secret.fail_on_server_error: false` under the authorized outage policy:
API unavailability is distinct from findings or a rejected configured key, and the
independent local gate remains required. The review suggestion to reverse this setting
does not supersede that policy.

## Budget and lint interpretations

Owner: FarDust. Planning assumption, not measured demand: 60 runs/month at three Linux
minutes each gives 180 minutes/month. At the dated USD 0.006/minute list-price catalog,
gross cost is USD 1.08/month. Standard public-repository runner treatment is a separate
discount; no correctness or availability decision depends on a free allowance.
The five-minute timeout is a bound, not proof of the target's achieved wall time.

Two generic ci-budget lint findings have explicit interpretations:

- `duplicate-trigger`: push is restricted to main; feature updates run through PRs.
  A merge's main-branch validation is distinct from its feature-head validation. Avoid
  opening a PR sourced from main, which would overlap those events.
- `long-lived-secret`: this is a GitGuardian API credential, not a cloud deployment
  credential. The documented ggshield integration requires an API key; cloud OIDC/WIF
  is not a substitute for this API. Keep cloud deployment identity outside this job.

## Alternatives and verification

Skipping Gitleaks, allowing every exit 128, disabling findings, compiling Gitleaks on
the production node, and using a self-hosted runner for this public repository were
rejected. No new credential was provisioned by this change.

Validate with actionlint, focused Linux tests and the actual range-scanning commands.
Review the exact published head independently. When Actions cannot acquire a runner,
record the actual billing/outage annotation and apply the approved independent local
fallback; a job that executes and fails remains a real failure. Merge only after the
coordinator's explicit PASS. This ADR does not claim hosted CI success.

Reference: https://docs.gitguardian.com/ggshield-docs/integrations/cicd-integrations/github-actions
