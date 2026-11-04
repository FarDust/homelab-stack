# Obsidian Remote Access

This stack supports two separate remote-access paths:

- Self-hosted LiveSync via CouchDB for human Obsidian clients.
- Obsidian Local REST API in the hosted Obsidian instance for MCP/agent access.

## Self-hosted LiveSync

LiveSync clients connect to CouchDB through Traefik:

```text
https://obsidian-livesync.${LOCAL_DOMAIN}
```

Generate the CouchDB password before deployment:

```bash
mkdir -p secrets/obsidian_livesync
openssl rand -base64 32 > secrets/obsidian_livesync/couchdb_password
chmod 600 secrets/obsidian_livesync/couchdb_password
```

The default CouchDB user is:

```text
obsidian_livesync
```

The default LiveSync database created for this stack is:

```text
obsidian
```

Override it by setting this before deploy if needed:

```bash
export OBSIDIAN_LIVESYNC_COUCHDB_USER=obsidian_livesync
```

Deploy the stack:

```bash
source .env
uv run cluster-utils deploy --help
```

Use the `productivity-knowledge` stack / `stacks/productivity/knowledge.yml` target from the deploy utility.

### Plugin Setup

On the first Obsidian client:

1. Install the `Self-hosted LiveSync` community plugin.
2. Choose CouchDB as the remote type.
3. Use `https://obsidian-livesync.${LOCAL_DOMAIN}` as the remote URL.
4. Use database `obsidian`.
5. Use the CouchDB user/password above.
6. Run the plugin's database check/fix flow if prompted.
7. Enable end-to-end encryption.
8. Enable path obfuscation.
9. Generate a setup URI and store it outside the vault.

On each additional Obsidian client, import that setup URI and choose the secondary/subsequent-device flow.

Do not mix this vault with Obsidian Sync or another live sync provider at the same time.

## Local REST API for MCP

Install the `Local REST API` community plugin in the hosted Obsidian instance at:

```text
https://obsidian.${LOCAL_DOMAIN}
```

The plugin provides HTTPS REST endpoints, including:

```text
/vault/{path}
/active/
/periodic/{period}/
/search/simple/
/search/
/commands/
/tags/
/open/{path}
```

It is useful for MCP/agent access because agents can target a single always-on Obsidian instance instead of needing local MCP setup on each PC.

Important: the plugin defaults to `https://127.0.0.1:27124`. Before exposing it through Traefik, verify from inside the Obsidian container whether it can listen on an address reachable by Traefik. If it cannot, add a loopback-to-overlay forwarder or sidecar rather than weakening the REST API authentication.

Keep both protections enabled when exposing the REST API:

- Traefik route restricted to `${LOCAL_DOMAIN}` / VPN access.
- The plugin's bearer-token authentication.
