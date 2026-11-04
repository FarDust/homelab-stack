# Remove the Infinity vector database

- Status: accepted 2026-10-12 (owner decision)

## Context

`main-storage_infinity` (infiniflow/infinity v0.6.15) was deployed as the vector store for RAGFlow, but RAGFlow never worked (`retrieval-documents_ragflow` is at 0/0) and nothing else in the stacks references Infinity. During the 2026-10-12 frost-fang incident, Infinity wrote about 900,000 log lines in 3 hours across 11 task restarts. That adds I/O load on a node that was already saturated. The owner plans to move to a different vector database.

## Decision

Remove the `infinity` service and its `infinity_conf` config from `stacks/main/storage.yml`, and remove the live service. Keep the `infinity_data` volume declaration and its data, so nothing is lost.

## Alternatives

- **Keep it at 0 replicas:** rejected. It is dead configuration that a redeploy would bring back.
- **Upgrade it:** not pursued. No release note was found establishing a stability fix, and there is no consumer.

## Consequences

The Traefik routes `infinity.*`, `infinity-thrift.*` and `infinity-api.*` disappear. A future vector database is a separate decision. The volume can be deleted later on an explicit request.

## Verification

`docker service ls` no longer lists `main-storage_infinity`. The stack renders without the service. The evidence logs are kept in the private deployment records.
