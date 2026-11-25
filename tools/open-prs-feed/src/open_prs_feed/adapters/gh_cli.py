"""Open PRs through the GitHub CLI (`gh pr list`); the CLI owns authentication and the API client."""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PositiveInt, TypeAdapter, ValidationError

from open_prs_feed.adapters.process import CommandRunner, tail
from open_prs_feed.domain.errors import MalformedSourceError, SourceUnavailableError, TruncatedSourceError
from open_prs_feed.domain.models import OpenPr

FIELDS = "number,headRefOid,headRefName,updatedAt"


class _GhPr(BaseModel):
    """One row of `gh pr list --json number,headRefOid,headRefName,updatedAt`. Every field is required."""

    model_config = ConfigDict(extra="ignore", strict=True)

    number: PositiveInt
    headRefOid: str = Field(pattern=r"^[0-9a-f]{40}$")
    headRefName: str = Field(min_length=1)
    updatedAt: AwareDatetime = Field(strict=False)


_ROWS = TypeAdapter(list[_GhPr])


class GhCliSource:
    def __init__(self, runner: CommandRunner, gh_command: Sequence[str], limit: int, timeout_s: float) -> None:
        if limit < 2:
            raise ValueError("limit must be at least 2 so a full page can be told apart from a complete answer")
        self._runner = runner
        self._gh = list(gh_command)
        self._limit = limit
        self._timeout_s = timeout_s

    def open_prs(self, repo: str) -> list[OpenPr]:
        argv = [
            *self._gh,
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(self._limit),
            "--json",
            FIELDS,
        ]
        try:
            res = self._runner.run(argv, None, self._timeout_s)
        except FileNotFoundError as exc:
            raise SourceUnavailableError(f"{self._gh[0]} not found while listing open PRs of {repo}") from exc
        except TimeoutError as exc:
            raise SourceUnavailableError(f"listing open PRs of {repo}: {exc}") from exc
        if res.returncode != 0:
            raise SourceUnavailableError(
                f"gh pr list for {repo} exited {res.returncode}: {tail(res.stderr) or '(no stderr)'}"
            )
        try:
            raw = json.loads(res.stdout.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MalformedSourceError(f"gh pr list for {repo} did not print JSON: {tail(res.stdout)!r}") from exc
        try:
            rows = _ROWS.validate_python(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            raise MalformedSourceError(f"gh pr list for {repo}: row field {where}: {first['msg']}") from exc
        if len(rows) >= self._limit:
            raise TruncatedSourceError(f"{repo} returned {len(rows)} open PRs, the --limit; raise the limit")
        numbers = [r.number for r in rows]
        if len(set(numbers)) != len(numbers):
            raise MalformedSourceError(f"gh pr list for {repo} repeated a PR number")
        return [
            OpenPr(
                repo=repo,
                number=r.number,
                head_sha8=r.headRefOid[:8],
                branch=r.headRefName,
                updated_at=r.updatedAt,
            )
            for r in rows
        ]
