#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "typer>=0.12", "rich>=13"]
# ///
"""Ask the cluster PR-Agent A2A service to review a pull request or a diff.

Exit codes: 0 review completed, 1 task failed or returned no review, 2 transport/protocol error.
A failed review is never reported as success (see docs/adr/pr_agent_ci_adr.md).
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console

app = typer.Typer(add_completion=False, help=__doc__)
err = Console(stderr=True)
TERMINAL = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}


def _task(payload: dict) -> dict:
    if "error" in payload:
        raise RuntimeError(f"JSON-RPC error: {str(payload['error'])[:300]}")
    result = payload["result"]
    return result["task"] if "task" in result else result


def _text(task: dict) -> str:
    parts = [p for a in task.get("artifacts") or [] for p in a.get("parts") or []]
    return "".join(p.get("text", "") for p in parts)


@app.command()
def review(
    pr_url: Annotated[str | None, typer.Option(help="GitHub pull request URL to review")] = None,
    diff_file: Annotated[Path | None, typer.Option(help="Review this unified diff instead of a PR URL")] = None,
    command: Annotated[str, typer.Option(help="review | describe | improve")] = "review",
    url: Annotated[str, typer.Option(envvar="PR_AGENT_URL", help="Base URL of the PR-Agent service")] = "",
    token: Annotated[str, typer.Option(envvar="PR_AGENT_TOKEN", help="Bearer token")] = "",
    timeout: Annotated[int, typer.Option(help="Seconds to wait for the review")] = 600,
    output: Annotated[Path | None, typer.Option(help="Write the review markdown here")] = None,
) -> None:
    if not url or not token:
        err.print("PR_AGENT_URL and PR_AGENT_TOKEN are required")
        raise typer.Exit(2)
    if (pr_url is None) == (diff_file is None):
        err.print("pass exactly one of --pr-url or --diff-file")
        raise typer.Exit(2)
    body = f"{command} {pr_url}" if pr_url else f"{command} the following\n```diff\n{diff_file.read_text()}\n```"
    headers = {"Authorization": f"Bearer {token}", "A2A-Version": "1.0", "Content-Type": "application/json"}
    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": body}]}},
    }
    deadline = time.monotonic() + timeout
    try:
        with httpx.Client(base_url=url.rstrip("/"), headers=headers, timeout=timeout) as client:
            response = client.post("/", json=request)
            response.raise_for_status()
            task = _task(response.json())
            while task["status"]["state"] not in TERMINAL:
                if time.monotonic() > deadline:
                    err.print(f"timed out after {timeout}s in state {task['status']['state']}")
                    raise typer.Exit(1)
                time.sleep(5)
                poll = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "GetTask", "params": {"id": task["id"]}}
                reply = client.post("/", json=poll)
                reply.raise_for_status()
                task = _task(reply.json())
    except (httpx.HTTPError, RuntimeError, KeyError) as exc:
        err.print(f"transport or protocol error: {type(exc).__name__}: {str(exc)[:300]}")
        raise typer.Exit(2) from exc
    state = task["status"]["state"]
    text = _text(task)
    if state != "TASK_STATE_COMPLETED" or not text.strip() or "no output produced" in text:
        err.print(f"review not completed: state={state}\n{text[:500]}")
        raise typer.Exit(1)
    if output:
        output.write_text(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    app()
