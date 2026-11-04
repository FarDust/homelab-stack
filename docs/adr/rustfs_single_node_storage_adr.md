# RustFS single-node storage

## Context

A cluster-local S3-compatible service supports application object storage. Its data must survive container replacement without assuming that Docker local volumes follow tasks between nodes.

## Decision

Run the official version-pinned RustFS image with one replica, a named local data volume and existing non-ephemeral storage-manager placement constraints. Load root credentials from Docker secrets and make the S3 endpoint available on the internal cluster network. Keep the console disabled.

## Alternatives

Distributed RustFS needs multiple independent failure domains and suitable disks; S3-over-FUSE and rclone introduce additional consistency and availability considerations. This initial deployment does not claim distributed availability or replace the existing object storage.

## Consequences

The service depends on its storage node; a local volume is not node-failover storage. The volume must be included in a validated backup and recovery process before it stores irreplaceable data. OAuth refresh tokens require separate persistence and concurrency validation.

## Verification

Render the stack, check the service and readiness endpoint, and exercise authenticated S3 create, write, read, delete and cleanup. Check replacement and backup recovery before claiming durable application integration.
