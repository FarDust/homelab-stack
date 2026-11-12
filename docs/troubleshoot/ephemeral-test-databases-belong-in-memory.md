# Ephemeral test databases belong in memory

A throwaway PostgreSQL started for a test or QA run fsyncs every commit. With its data directory in an anonymous Docker volume on a hard-disk-backed Docker root, one such container measured 143 MB and 6,006 write operations in 60 seconds: 63 % of the bytes written to that volume and the largest single cause of I/O pressure on the node while it ran. The anonymous volume also stays behind when the container is removed without `-v`.

Start throwaway databases with the data directory in memory:

```bash
docker run --rm --name my-test-pg \
  --tmpfs /var/lib/postgresql/data:rw,size=2g \
  -e POSTGRES_PASSWORD="$TEST_PG_PASSWORD" \
  postgres:17-alpine -c fsync=off -c synchronous_commit=off -c full_page_writes=off
```

- `--tmpfs` keeps the data off the disk and leaves no volume behind; size it to the test data.
- The three settings are safe only because the data is disposable. Keep them away from any database whose contents matter.
- Use `--rm` (or `docker rm -v`) so no anonymous volume survives the run.

Decision record: [HDD-backed node I/O budget](../adr/hdd_node_io_budget_adr.md).
