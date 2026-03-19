# Hobby Stack

This directory contains hobby and media services for the Docker Swarm cluster.

## Services Overview

- **gaming.yml**: Pterodactyl game server panel and related services.
- **iot.yml**: Home Assistant, Mosquitto MQTT broker.
- **science.yml**: BOINC distributed computing.
- **streaming.yml**: Media stack (qBittorrent, Prowlarr, Sonarr, Radarr, Bazarr, Jellyfin, Jellyseerr). Requires `NFS_MEDIA_HOST` in `.env` for NFS volumes.

## Streaming (streaming.yml) – integration guide

Step-by-step setup for qBittorrent, Prowlarr (indexer), Sonarr, Radarr, Bazarr, Jellyfin, and Jellyseerr. Order matters: configure download client and indexers first, then the *arr apps, then Jellyfin and Jellyseerr.

**Prerequisites:** Stack deployed (e.g. `uv run cluster-utils deploy ...`), VPN or network access to `https://<service>.${LOCAL_DOMAIN}`. Set `NFS_MEDIA_HOST` (e.g. your NFS server IP or hostname) in `.env` before deploy.

---

### 1. qBittorrent

- **URL:** `https://qbittorrent.${LOCAL_DOMAIN}` (or your Traefik host)
- **First login:** Use the default Web UI credentials and change them immediately in Web UI → Tools → Options → Web UI.

**Do:**

1. Log in and change the Web UI password.
2. (Optional) Tools → Options → Connection: check "Use UPnP / NAT-PMP" if you want incoming connections without manual port forward.
3. Create categories (optional but useful for Sonarr/Radarr):
   - **tv** — for Sonarr
   - **movies** — for Radarr
   (Sonarr/Radarr will use these when adding the download client.)

**Note for later:** Download client hostname from other services in this stack = **`qbittorrent`** (same Docker network). Port = **8080** (Web UI). Use the username/password you set.

---

### 2. FlareSolverr (optional)

- **URL:** Internal only (`http://flaresolverr:8191`). Used by Prowlarr for Cloudflare‑protected indexer sites.

No UI. If you use Prowlarr and some indexers fail with Cloudflare, set FlareSolverr in Prowlarr: **Settings → Apps → add FlareSolverr**, URL `http://flaresolverr:8191`.

---

### 3. Indexers: Prowlarr

- **URL:** `https://prowlarr.${LOCAL_DOMAIN}`

1. Open Prowlarr → **Indexers** → **Add Indexer**. Add the trackers you want (public/private).
2. For indexers behind Cloudflare: **Settings → Apps → FlareSolverr**, add URL `http://flaresolverr:8191`.
3. **Settings → Apps:** Add **Sonarr** and **Radarr** (URLs `http://sonarr:8989` and `http://radarr:7878`, API key from each app’s Settings → General). Enable "Sync App Indexers" so indexers are pushed to Sonarr/Radarr.

---

### 4. Sonarr (TV)

- **URL:** `https://sonarr.${LOCAL_DOMAIN}`

1. **Settings → General:** Copy or note the **API Key** (needed for Prowlarr and Jellyseerr).
2. **Settings → Download Clients → +** Add **qBittorrent**:
   - Host: **`qbittorrent`**
   - Port: **8080**
   - Username / password: the Web UI credentials you set in step 1.
   - Category: **tv** (if you created it).
   - Test and save.
3. **Settings → Indexers:** Indexers sync from Prowlarr (see step 3); ensure Sonarr is added as an app in Prowlarr with "Sync App Indexers" enabled. Set categories (e.g. 5000, 5030 for TV) as needed.
4. Add root folder: **/tv** (maps to your `tv_data` volume).

---

### 5. Radarr (movies)

- **URL:** `https://radarr.${LOCAL_DOMAIN}`

1. **Settings → General:** Note the **API Key** (for Prowlarr and Jellyseerr).
2. **Settings → Download Clients → +** Add **qBittorrent**:
   - Host: **`qbittorrent`**
   - Port: **8080**
   - Username / password: same as step 1.
   - Category: **movies** (if you created it).
   - Test and save.
3. **Settings → Indexers:** Indexers sync from Prowlarr (see step 3); ensure Radarr is added as an app in Prowlarr. Use movie categories (e.g. 2000, 2010) as needed.
4. Add root folder: **/movies** (maps to your `movies_data` volume).

---

### 6. Bazarr (subtitles)

- **URL:** `https://bazarr.${LOCAL_DOMAIN}`

1. Open Bazarr and complete the initial wizard.
2. Add Sonarr and Radarr:
   - **Sonarr URL:** `http://sonarr:8989`
   - **Radarr URL:** `http://radarr:7878`
   - Use API keys from each app (Settings → General).
3. Path mappings should align with this stack:
   - TV path: `/tv`
   - Movies path: `/movies`
4. Configure subtitle providers/languages as desired.

---

### 7. Jellyfin (playback)

- **URL:** `https://jellyfin.${LOCAL_DOMAIN}`

1. First run: create admin user and set libraries.
2. **Add Media Libraries:**
   - **TV:** path **/data/tvshows** (maps to `tv_data`).
   - **Movies:** path **/data/movies** (maps to `movies_data`).
   Use the content type (TV Shows / Movies) and any metadata options you prefer.
3. Finish setup. Note the server URL and admin account for Jellyseerr.

---

### 8. Jellyseerr (requests)

- **URL:** `https://jellyseerr.${LOCAL_DOMAIN}`

1. Sign in with your Jellyfin user (or create one in Jellyfin first).
2. **Settings → Services:**
   - **Jellyfin:** server URL `https://jellyfin.${LOCAL_DOMAIN}` (or internal `http://jellyfin:8096`), API key from Jellyfin Dashboard → API Keys.
   - **Sonarr:** server URL `http://sonarr:8989`, API key from Sonarr Settings → General.
   - **Radarr:** server URL `http://radarr:7878`, API key from Radarr Settings → General.
3. **Settings → Users:** set request limits and permissions if needed.
4. Users can then request TV/movies from Jellyseerr; it talks to Sonarr/Radarr, which send downloads to qBittorrent.

---

### Quick reference – internal hostnames

| Service      | Internal URL (from other containers) |
|-------------|--------------------------------------|
| qBittorrent | `qbittorrent:8080`                   |
| FlareSolverr| `http://flaresolverr:8191`           |
| Prowlarr    | `http://prowlarr:9696`               |
| Sonarr      | `http://sonarr:8989`                 |
| Radarr      | `http://radarr:7878`                 |
| Bazarr      | `http://bazarr:6767`                 |
| Jellyfin    | `http://jellyfin:8096`               |

Use these when one service needs to call another (e.g. Prowlarr → Sonarr, Jellyseerr → Sonarr/Radarr/Jellyfin).

---

### Troubleshooting

- **Sonarr/Radarr "Unable to connect" to qBittorrent:** Ensure host is `qbittorrent`, port 8080, and Web UI is enabled with correct credentials.
- **Indexer errors / Cloudflare:** Configure FlareSolverr in Prowlarr (Settings → Apps) and ensure the indexer is enabled for FlareSolverr where supported.
- **No results in *arr:** Check indexers are added and (with Prowlarr) that sync ran; in Sonarr/Radarr run a manual search to test.
- **Jellyseerr can’t reach Sonarr/Radarr/Jellyfin:** Use internal URLs (`http://sonarr:8989` etc.) and valid API keys from each app.
- **"Folder '/tv/' (or '/movies/') is not writable by user 'abc'":** The media volume is owned by root; Sonarr/Radarr run as `abc` (PUID/PGID). On the **node where the service runs** (e.g. `docker service ps hobby-streaming_sonarr` to find it), run:
  - Sonarr: `docker run --rm -v hobby-streaming_tv_data:/tv alpine chown -R 1000:1000 /tv`
  - Radarr: `docker run --rm -v hobby-streaming_movies_data:/movies alpine chown -R 1000:1000 /movies`
  Use your actual PUID:PGID from `.env` if not 1000:1000.
