# ComfyUI rclone cache retention

- Status: accepted 2026-10-12 (owner decision); applies when the volumes are recreated
- Owner decision: keep the ComfyUI cache 7 days (14 at most), and never let it fill the disk

## Context

The ComfyUI volumes (`comfyui_custom_nodes`, `comfyui_data`, `comfyui_models`, `comfyui_output`, `comfyui_config`) use the rclone plugin with `vfs_cache_mode: full` and rclone's default `vfs_cache_max_age` of 1 h. A model unused for an hour is evicted and downloaded again from GCS on its next use. GCS egress to the home network is expensive, and the models are several GB each. `ollama_data` already uses `168h` with `64G`.

## Decision

Every ComfyUI rclone volume sets `vfs_cache_max_age: 168h`, a per-volume `vfs_cache_max_size`, and `vfs_cache_min_free_space: 15G`:

| Volume | `vfs_cache_max_size` |
| --- | --- |
| models | 48G |
| data | 8G |
| output | 8G |
| custom_nodes | 4G |
| config | 1G |

The cache is evicted least-recently-used first when a cap or the free-space floor is reached. Caps are checked every `--vfs-cache-poll-interval` (1 min), and open files are never evicted.

## Alternatives

- **Keep the 1 h default:** rejected, because of repeated egress.
- **Unbounded retention:** rejected, because the cache could fill the node's disk.
- **14 days:** acceptable to the owner; 7 days chosen as the default.

## Consequences

- Volume `driver_opts` are fixed when a volume is created. The existing volumes on the GPU node (gabriel-pc-wsl) must be removed and recreated: the data stays in GCS, and the local cache refills once.
- `comfyui_models` (`comfyui/data/models`) overlaps `comfyui_data` (`comfyui/data`). That overlap is still open; separating the volumes needs a bucket layout change.

## Verification

After recreation, check that `docker volume inspect` shows the new options, that the cache directory size stays under the caps, and that GCS egress shows no repeated model downloads.
