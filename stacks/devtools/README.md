# Devtools Stack

This stack hosts notebook runtimes exposed through Traefik for development workflows.

## Services

- `jupyter-tensorflow`: High-end GPU Colab runtime (`priority=100`)
- `jupyter-tensorflow-low-end`: Low-end GPU fallback (`priority=50`)

Both services use:

- `Host(\`colab.${LOCAL_DOMAIN}\`)`
- `websecure` entrypoint
- `traefik-public` network
- deterministic auth token from `${JUPYTER_TOKEN}`
- shared rclone/GCS-backed persistence paths for:
  - `/home/jovyan/work`
  - `/home/jovyan/.venvs`
- rclone plugin-compatible options (`vfs_links=true`; avoid unsupported `links=true`)
- `uv` bootstrap hook (`configs/notebooks/uv-bootstrap.sh`) for runtime alignment

Runtime bootstrap mode:

- high-end service writes/repairs shared environments (`UV_BOOTSTRAP_ENABLED=true`)
- low-end service runs in follower mode (`UV_BOOTSTRAP_ENABLED=false`) to avoid concurrent writes on shared storage

## Deploy

From repo root:

```bash
set -a; source .env; set +a
uv run cluster-utils deploy service jupyter-tensorflow \
  --compose-file stacks/devtools/notebooks.yml \
  --stack-name devtools-notebooks \
  --bump-config \
  --timeout 900

uv run cluster-utils deploy service jupyter-tensorflow-low-end \
  --compose-file stacks/devtools/notebooks.yml \
  --stack-name devtools-notebooks \
  --timeout 900
```

Validate:

```bash
docker stack services devtools-notebooks
curl -s "https://colab.${LOCAL_DOMAIN}/api/kernelspecs?token=${JUPYTER_TOKEN}" | jq '.kernelspecs | keys'
```

## Colab Local Runtime Connection

Direct URL to the Traefik hostname is usually rejected by Colab UI validation.
Colab expects a localhost backend URL.

Use:

```text
http://127.0.0.1:8888/?token=<JUPYTER_TOKEN>
```

## macOS Caddy Workaround (recommended)

Create a local HTTP proxy on `127.0.0.1:8888` that forwards to Traefik and sets the expected upstream host header.
The local listener must stay HTTP (not HTTPS) because Colab probes `http://127.0.0.1:8888/...`.

Install:

```bash
brew install caddy
```

Create persistent service config (fish-safe, no heredoc):

```fish
set -gx COLAB_FQDN "colab.<LOCAL_DOMAIN>"

printf '%s\n' \
'{' \
'  auto_https off' \
'}' \
'http://127.0.0.1:8888 {' \
'  bind 127.0.0.1' \
"  reverse_proxy https://$COLAB_FQDN:443 {" \
"    header_up Host $COLAB_FQDN" \
'    transport http {' \
'      dial_timeout 20s' \
"      tls_server_name $COLAB_FQDN" \
'    }' \
'  }' \
'}' > /opt/homebrew/etc/Caddyfile
```

Start service:

```bash
brew services restart caddy
brew services list | grep caddy
```

Test:

```bash
curl -v "http://127.0.0.1:8888/api/sessions?token=<JUPYTER_TOKEN>"
curl -v "http://127.0.0.1:8888/api/kernelspecs?token=<JUPYTER_TOKEN>"
```

Expected: HTTP `200`.

Confirm it is not exposed on LAN:

```bash
lsof -nP -iTCP:8888 -sTCP:LISTEN
```

Expected listener: `127.0.0.1:8888` only.

## Brave Browser Note

If Colab shows `ERR_BLOCKED_BY_CLIENT`, Brave Shields or an extension is blocking localhost requests from Colab.

Fix:

1. Disable Shields for `colab.research.google.com`.
2. Disable blocker/privacy extensions for that site.
3. Hard refresh and reconnect.

If needed, verify in a clean Chrome profile first to isolate browser blocking vs runtime issues.

## Secret Handling

Do not hardcode tokens in config files, docs, screenshots, or issue comments.
Use placeholders in documentation and read token values from your local environment/session only.
