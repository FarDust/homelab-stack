"""Check this worker's actual RQ heartbeat, including during busy execution."""

import os
from datetime import UTC, datetime

from redis import Redis
from rq import Worker

from rq_settings import REDIS_URL

with Redis.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=5) as connection:
    connection.ping()
    worker = Worker.find_by_key(f"rq:worker:{os.environ['HOSTNAME']}", connection=connection)
    if worker is None or worker.last_heartbeat is None:
        raise SystemExit(1)
    age = (datetime.now(UTC) - worker.last_heartbeat).total_seconds()
    raise SystemExit(0 if age < 120 else 1)
