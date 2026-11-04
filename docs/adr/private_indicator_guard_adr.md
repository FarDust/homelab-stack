# Private indicator guard

## Context

This repository is public, while the cluster it describes is private. Commits have carried identifiers that belong to the
private deployment: hostnames and domains, Tailscale addresses, owner-identifying bucket names, account identifiers,
personal e-mail addresses, and whole files such as live environment backups and reports. A secret scanner does not catch
these, because they are not credentials.

## Decision

A local pre-commit hook, `scripts/check_private_indicators.py`, inspects only what a commit adds and rejects it when it finds:

- Generic indicators that need no private knowledge: Tailscale CGNAT addresses (except the public MagicDNS resolver), `*.ts.net`
  names, bucket names that embed a numeric project id, and consumer e-mail addresses.
- Entries of a private deny-list, read from the file named by `PRIVATE_INDICATORS_FILE` (default `.git/private-indicators.txt`).
  Git never tracks that file, so the list of real values stays out of history. Findings name the rule number, never the value.
- Paths that never belong here: `reports/`, `docs/reports/`, live environment backups, timestamped backups, agent state
  directories and generated graph output.

Configuration that is cluster specific belongs in environment variables, in private folders, or in private sub-repositories.

## Alternatives

- A shared deny-list committed to the repository was rejected because the list would itself publish the indicators.
- Relying on the secret scanners was rejected because the indicators are not credentials.
- A server-side check only was rejected because history that reaches the remote cannot be rewritten.

## Consequences

Each contributor machine keeps its own deny-list file; the generic rules and path rules work everywhere. A false positive is
fixed by replacing the value with a variable or placeholder. The hook does not scan history that already exists on the remote.

## Verification

Run the hook against a staged change that contains a CGNAT address, a consumer e-mail, a bucket-with-project-id name, a
deny-list entry and a file under `reports/`: it exits 1 and prints no values. Run it against a change that only uses
environment-variable placeholders: it exits 0.
