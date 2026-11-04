"""Owned live AMQP/RQ probes; credentials arrive on stdin, never in arguments."""

import json
import sys
import time

import pika
import typer
from redis import Redis
from rq import Queue, Retry
from rq.job import Job
from rq.serializers import JSONSerializer

from rq_settings import REDIS_URL

app = typer.Typer(pretty_exceptions_show_locals=False)


@app.command()
def prepare(run: str) -> None:
    """Publish confirmed messages and enqueue real importable RQ jobs."""
    password = sys.stdin.read().strip()
    parameters = pika.ConnectionParameters(
        host="main-messaging_rabbitmq", virtual_host="platform",
        credentials=pika.PlainCredentials("platform", password),
        socket_timeout=10, blocked_connection_timeout=10,
    )
    with pika.BlockingConnection(parameters) as connection:
        channel = connection.channel()
        channel.confirm_delivery()
        channel.exchange_declare(exchange=run + ".dlx", exchange_type="direct", durable=True)
        channel.queue_declare(queue=run + ".dlq", durable=True,
                              arguments={"x-queue-type": "quorum"})
        channel.queue_bind(queue=run + ".dlq", exchange=run + ".dlx", routing_key="failed")
        channel.queue_declare(queue=run + ".work", durable=True, arguments={
            "x-queue-type": "quorum", "x-dead-letter-exchange": run + ".dlx",
            "x-dead-letter-routing-key": "failed", "x-overflow": "reject-publish",
            "x-max-length": 100, "x-delivery-limit": 5,
        })
        for body in (b"acknowledged", b"dead-letter", b"survives-restart"):
            channel.basic_publish(exchange="", routing_key=run + ".work", body=body,
                                  properties=pika.BasicProperties(delivery_mode=2), mandatory=True)
        method, _, body = channel.basic_get(queue=run + ".work", auto_ack=False)
        assert method is not None and body == b"acknowledged"
        channel.basic_ack(method.delivery_tag)
        method, _, body = channel.basic_get(queue=run + ".work", auto_ack=False)
        assert method is not None and body == b"dead-letter"
        channel.basic_nack(method.delivery_tag, requeue=False)
    with Redis.from_url(REDIS_URL) as redis:
        queue = Queue("cluster.example.v1", connection=redis, serializer=JSONSerializer)
        for suffix, function, args, retry in (
            ("success", "jobs_v1.echo", (run,), None),
            ("retry", "jobs_v1.retry_once", (run,), Retry(max=1, interval=2)),
            ("restart", "jobs_v1.delayed_echo", (run, 60), None),
        ):
            queue.enqueue(function, args=args, job_id=run.replace(".", "-") + "-" + suffix,
                          job_timeout=120, result_ttl=86400, failure_ttl=86400, retry=retry)
    print(json.dumps({"run": run, "confirmed_publish": 3, "ack": 1, "nack_to_dlq": 1,
                      "rq_enqueued": 3}))


@app.command()
def verify(run: str) -> None:
    """Check persistent AMQP/DLQ bodies and retained RQ results after replacements."""
    password = sys.stdin.read().strip()
    parameters = pika.ConnectionParameters(
        host="main-messaging_rabbitmq", virtual_host="platform",
        credentials=pika.PlainCredentials("platform", password),
        socket_timeout=10, blocked_connection_timeout=10,
    )
    with pika.BlockingConnection(parameters) as connection:
        channel = connection.channel()
        for suffix, expected in (("work", b"survives-restart"), ("dlq", b"dead-letter")):
            method, properties, body = channel.basic_get(queue=run + "." + suffix, auto_ack=False)
            assert method is not None and body == expected, (suffix, body)
            assert properties.delivery_mode == 2
            if suffix == "dlq":
                assert properties.headers["x-death"][0]["reason"] == "rejected"
            channel.basic_ack(method.delivery_tag)
            assert channel.queue_declare(queue=run + "." + suffix, passive=True).method.message_count == 0
        channel.queue_delete(queue=run + ".work")
        channel.queue_delete(queue=run + ".dlq")
        channel.exchange_delete(exchange=run + ".dlx", if_unused=True)
    with Redis.from_url(REDIS_URL) as redis:
        deadline = time.monotonic() + 150
        for suffix in ("success", "retry", "restart"):
            job = Job.fetch(run.replace(".", "-") + "-" + suffix, connection=redis, serializer=JSONSerializer)
            while job.get_status(refresh=True).value != "finished" and time.monotonic() < deadline:
                time.sleep(1)
            assert job.return_value(refresh=True) == run, (suffix, job.get_status())
            if suffix == "retry":
                assert job.meta["first_attempt_observed"] is True
                assert job.retries_left == 0
            assert redis.ttl(job.key) > 0
            print(json.dumps({"job": job.id, "status": job.get_status().value,
                              "result": run, "result_retained": True}))
    print(json.dumps({"broker_restart_persistence": True, "dlq_restart_persistence": True,
                      "owned_broker_resources_cleaned": True}))


if __name__ == "__main__":
    app()
