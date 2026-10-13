# Loki failover, failback and restore

Decision and design: `docs/adr/loki_local_primary_backup_adr.md`. Tested on 2026-10-13 (restore from GCS, failover drill from the replica copy). Services: `main-logging_loki`, `main-logging_loki-replica` (manager), `main-logging_loki-sync` (Loki node). Marker file: `/var/lib/docker/loki-store/.loki-store-initialized`; without it Swarm refuses to start Loki on that node. After a restore or seed create it by hand: `sudo sh -c 'date -u +%FT%TZ > /var/lib/docker/loki-store/.loki-store-initialized'`.


Names assume the services are added to stack `main-logging` (`main-logging_loki`, `main-logging_loki-replica`, `main-logging_loki-sync`). Hosts: fardustdev = manager/leader (replica), frost-fang = Loki + sync.

## One-time setup
```sh
# fardustdev (root): replica directory and secret
sudo install -d -m 0755 /var/lib/docker/loki-store
printf '%s' "$(head -c 32 /dev/urandom | base64 | tr -d '/+=\n')" | docker secret create loki_replica_pass_2 -
# frost-fang (root), after the seed: marker file next to the data
sudo sh -c 'date -u +%FT%TZ > /var/lib/docker/loki-store/.loki-store-initialized'
# pre-pull Loki on the failover node so a failover is not waiting on a registry
docker pull grafana/loki:3.6.4        # run on fardustdev (image already pulled there on 2026-10-13)
```
Deploy: merge `loki-replica.compose.yml` and `loki-sync.compose.yml` into `stacks/main/logging.yml` (the `configs:` entry `loki_sync_script` points at `./configs/logging/loki-sync.sh`), then `docker stack deploy`.

Initial seed, after the marker exists (both are nice/ionice/bandwidth limited and I/O gated):
```sh
S=$(docker ps -q -f name=main-logging_loki-sync)          # on frost-fang
docker exec $S /bin/sh /scripts/loki-sync.sh run replica full
docker exec $S /bin/sh /scripts/loki-sync.sh run gcs full
docker exec $S /bin/sh /scripts/loki-sync.sh run check
```
Measured on 2 GB: replica seed 11 min, GCS seed 12 min, check 1 min (replica) + 30 s (GCS).

## Failover (frost-fang or its Loki is lost; data on fardustdev is the replica, at most about 5 minutes old)
```sh
# 1. If frost-fang is still reachable: stop Loki cleanly (flush_on_shutdown, 2 m grace), then one last copy
docker service scale main-logging_loki=0
ssh frost-fang 'docker exec $(docker ps -q -f name=main-logging_loki-sync) /bin/sh /scripts/loki-sync.sh run replica incr'
# 2. Stop the writers into the replica directory (the sync job pushes to it, the webdav server serves it)
docker service scale main-logging_loki-sync=0 main-logging_loki-replica=0
# 3. Check the directory and the marker on fardustdev
ssh fardustdev (root) 'sudo ls -la /var/lib/docker/loki-store/.loki-store-initialized; sudo ls /var/lib/docker/loki-store'
# 4. Move the pinned service to the leader (flip the constraint, keep storage.manager == true)
docker service update --constraint-rm 'node.labels.swarm.leader != true' \
  --constraint-add 'node.labels.swarm.leader == true' main-logging_loki
docker service scale main-logging_loki=1
# 5. Verify: task on fardustdev, ready, data answers
docker service ps main-logging_loki --format '{{.Node}} {{.CurrentState}}' | head -1
docker service logs main-logging_loki --tail 20
# from a container on the traefik network (any service with wget):
#   wget -q -O- http://main-logging_loki:3100/ready
#   wget -q -O- 'http://main-logging_loki:3100/loki/api/v1/query?query=sum(count_over_time(%7Bjob%3D%22docker%22%7D%5B1h%5D))'
```
If Loki crashes on start because the best-effort WAL copy is inconsistent, move the WAL aside (losing at most the last 5 minutes) and restart:
`ssh fardustdev (root) 'sudo mv /var/lib/docker/loki-store/wal /var/lib/docker/loki-store/wal.bad-$(date +%s)'` then `docker service update --force main-logging_loki`.
Silence `LokiReplicaStale`, `LokiGcsCopyStale`, `LokiSyncAbsent` while failed over. A stack redeploy from git restores the `!= true` constraint; commit the intended constraint first or avoid redeploying the stack during the failover.

## Failback (frost-fang is back)
```sh
# 1. Stop Loki on fardustdev cleanly (flush_on_shutdown) and bring the replica webdav up on the same directory
docker service scale main-logging_loki=0
docker service scale main-logging_loki-replica=1
# 2. Mirror the directory back to frost-fang with the restore job (copies chunks without deleting, syncs wal/index/compactor, verifies)

LOKI_SYNC_SCRIPT=stacks/main/configs/logging/loki-sync.sh LOKI_RESTORE_FROM=replica LOKI_RESTORE_MODE=mirror LOKI_RESTORE_TARGET=/var/lib/docker/loki-store \
  docker stack deploy -c docs/troubleshoot/loki-restore-job.compose.yml loki-restore
docker service logs loki-restore_restore            # expect: "restored from replica into /restore ... verification ok"
docker stack rm loki-restore
# 3. Move Loki back and verify
docker service update --constraint-rm 'node.labels.swarm.leader == true' \
  --constraint-add 'node.labels.swarm.leader != true' main-logging_loki
docker service scale main-logging_loki=1
docker service ps main-logging_loki --format '{{.Node}} {{.CurrentState}}' | head -1
# 4. Resume the sync pair
docker service scale main-logging_loki-sync=1
docker exec $(ssh frost-fang 'docker ps -q -f name=main-logging_loki-sync') /bin/sh /scripts/loki-sync.sh run check   # run on frost-fang
```
Files that retention removed on fardustdev during the failover leave stale copies on frost-fang; the daily guarded prune removes files that vanished from the source.

## Restore from scratch (both nodes lost, or an empty directory to refill)
```sh
# from GCS (the target directory must exist and be empty; repeat on whichever node will run Loki)
sudo install -d -m 0755 /var/lib/docker/loki-store
LOKI_SYNC_SCRIPT=stacks/main/configs/logging/loki-sync.sh LOKI_RESTORE_FROM=gcs LOKI_RESTORE_TARGET=/var/lib/docker/loki-store \
  docker stack deploy -c docs/troubleshoot/loki-restore-job.compose.yml loki-restore
docker service logs loki-restore_restore; docker stack rm loki-restore
# from the replica: LOKI_RESTORE_FROM=replica (needs main-logging_loki-replica running)
```
Add `LOKI_RESTORE_CONSTRAINT='node.labels.swarm.leader == true'` to run the job on fardustdev. Measured: 2 GB from GCS in 167 s, from the replica in 249 s.
