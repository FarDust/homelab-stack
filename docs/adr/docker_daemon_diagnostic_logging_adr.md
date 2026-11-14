# ADR: Docker daemon diagnostic logging on the manager

Date: 2026-11-14. Status: accepted; live reload verified separately from source publication.

## Context

The manager has two CPUs. Debug logging was enabled in its Docker Engine 29.9.3 daemon configuration; a two-minute sample contained 7,688 daemon records, 7,555 of them debug-level. This added diagnostic output during normal service operation. CPU samples alone do not establish the share caused by logging.

## Decision

Keep the existing MTU and disable daemon debug logging in `host-config/docker/manager-daemon.json`. Preserve any additional live settings when applying this policy. Docker supports reloading the debug option using SIGHUP without a daemon restart: [dockerd configuration reload](https://docs.docker.com/reference/cli/dockerd/#configuration-reload-behavior).

Before a host change, compare the complete live configuration with the approved configuration and preserve unknown keys. Create one scoped rollback copy with its original ownership and mode; prepare an atomic same-directory replacement; validate it with `dockerd --validate --config-file <candidate>`; verify the daemon PID and start time; then use `systemctl reload docker`. Confirm `docker info` reports debug false, the same daemon remains active, container and service health are preserved, and the daemon log rate is measured over comparable windows. A reload can affect other reloadable keys, so verify the complete candidate and live effective settings before applying it.

## Alternatives

Leaving debug enabled keeps detailed diagnostics but continuously emits routine request and task logs. Restarting Docker to change logging would disrupt services and is unnecessary. Reducing monitoring or CPU concurrency leaves the diagnostic work in place.

## Consequences and rollback

Routine debug records are no longer available; warning and error diagnostics remain. This change does not resolve private-registry authentication, network failures or other CPU consumers. To roll back, validate and atomically restore the scoped original configuration, reload Docker without restarting it, then verify debug is true, daemon identity is unchanged and services remain healthy. Retain the rollback copy until independent source recovery and postcondition verification are complete.

## Verification

Check the candidate syntax and Docker validation, compare the source and deployed file hashes, confirm the reload without a PID change, compare container and service health, and sample daemon/journal CPU and log volumes before and after over stated windows. Record observed results separately from source readiness.
