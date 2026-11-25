"""Open PRs through the GitHub CLI; the CLI owns authentication, pagination and the API client."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    TypeAdapter,
    ValidationError,
)

from open_prs_feed.adapters.process import CommandRunner, tail
from open_prs_feed.domain.errors import MalformedSourceError, SourceUnavailableError, TruncatedSourceError
from open_prs_feed.domain.models import OpenPr

FIELDS = "number,headRefOid,headRefName,updatedAt"
OWNER_PRS_PER_REPO = 100

# Every non-archived repository the owner owns, with up to 100 open PRs each. A repository with more falls back to
# `gh pr list`. Keep `pageInfo` only on `repositories`: `gh --paginate` follows the single pageInfo in the query.
OWNER_QUERY = """
query($owner: String!, $endCursor: String) {
  repositoryOwner(login: $owner) {
    repositories(first: 100, after: $endCursor, ownerAffiliations: OWNER, isArchived: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        pullRequests(states: OPEN, first: __PER_REPO__) {
          totalCount
          nodes { number headRefOid headRefName updatedAt }
        }
      }
    }
  }
}
""".replace("__PER_REPO__", str(OWNER_PRS_PER_REPO))


class _GhPr(BaseModel):
    """One PR row as gh prints it. Every field is required."""

    model_config = ConfigDict(extra="ignore", strict=True)

    number: PositiveInt
    headRefOid: str = Field(pattern=r"^[0-9a-f]{40}$")
    headRefName: str = Field(min_length=1)
    updatedAt: AwareDatetime = Field(strict=False)


class _PrConnection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    totalCount: NonNegativeInt
    nodes: list[_GhPr]


class _Repo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    nameWithOwner: str = Field(min_length=3)
    pullRequests: _PrConnection


class _PageInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    hasNextPage: bool


class _Repos(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    pageInfo: _PageInfo
    nodes: list[_Repo]


class _Owner(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    repositories: _Repos


class _Data(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    repositoryOwner: _Owner  # null (unknown owner) fails validation


class _Page(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    data: _Data


_ROWS = TypeAdapter(list[_GhPr])
_PAGES = TypeAdapter(list[_Page])


def _first_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    return f"field {'.'.join(str(p) for p in first['loc'])}: {first['msg']}"


def _to_open_pr(repo: str, r: _GhPr) -> OpenPr:
    return OpenPr(repo=repo, number=r.number, head_sha8=r.headRefOid[:8], branch=r.headRefName, updated_at=r.updatedAt)


def _unique(repo: str, rows: list[_GhPr]) -> None:
    numbers = [r.number for r in rows]
    if len(set(numbers)) != len(numbers):
        raise MalformedSourceError(f"gh answer for {repo} repeated a PR number")


class GhCliSource:
    def __init__(
        self,
        runner: CommandRunner,
        gh_command: Sequence[str],
        limit: int,
        timeout_s: float,
        min_owner_repos: int = 1,
    ) -> None:
        if limit < 2:
            raise ValueError("limit must be at least 2 so a full page can be told apart from a complete answer")
        if min_owner_repos < 1:
            raise ValueError("min_owner_repos must be at least 1")
        self._min_owner_repos = min_owner_repos
        self._runner = runner
        self._gh = list(gh_command)
        self._limit = limit
        self._timeout_s = timeout_s

    def _json(self, what: str, args: list[str]) -> Any:
        argv = [*self._gh, *args]
        try:
            res = self._runner.run(argv, None, self._timeout_s)
        except FileNotFoundError as exc:
            raise SourceUnavailableError(f"{self._gh[0]} not found while listing open PRs of {what}") from exc
        except TimeoutError as exc:
            raise SourceUnavailableError(f"listing open PRs of {what}: {exc}") from exc
        if res.returncode != 0:
            raise SourceUnavailableError(f"gh for {what} exited {res.returncode}: {tail(res.stderr) or '(no stderr)'}")
        try:
            return json.loads(res.stdout.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MalformedSourceError(f"gh for {what} did not print JSON: {tail(res.stdout)!r}") from exc

    def open_prs(self, repo: str) -> list[OpenPr]:
        raw = self._json(
            repo,
            ["pr", "list", "--repo", repo, "--state", "open", "--limit", str(self._limit), "--json", FIELDS],
        )
        try:
            rows = _ROWS.validate_python(raw)
        except ValidationError as exc:
            raise MalformedSourceError(f"gh pr list for {repo}: row {_first_error(exc)}") from exc
        if len(rows) >= self._limit:
            raise TruncatedSourceError(f"{repo} returned {len(rows)} open PRs, the --limit; raise the limit")
        _unique(repo, rows)
        return [_to_open_pr(repo, r) for r in rows]

    def open_prs_of_owner(self, owner: str) -> list[OpenPr]:
        """Every open PR of every repository `owner` owns, from one paginated GraphQL query.

        Fewer visible repositories than `min_owner_repos` (a login that lost private scope, SSO or a token
        restriction) fails closed: those repositories' PRs would otherwise look closed.
        """
        raw = self._json(
            f"owner {owner}",
            ["api", "graphql", "--paginate", "--slurp", "-f", f"owner={owner}", "-f", f"query={OWNER_QUERY}"],
        )
        if isinstance(raw, list) and any(isinstance(p, dict) and "errors" in p for p in raw):
            raise SourceUnavailableError(f"GraphQL errors for owner {owner}: {json.dumps(raw)[:400]}")
        try:
            pages = _PAGES.validate_python(raw)
        except ValidationError as exc:
            raise MalformedSourceError(f"gh api graphql for owner {owner}: {_first_error(exc)}") from exc
        if not pages or pages[-1].data.repositoryOwner.repositories.pageInfo.hasNextPage:
            raise TruncatedSourceError(f"owner {owner}: pagination did not reach the last page of repositories")
        repos = [repo for page in pages for repo in page.data.repositoryOwner.repositories.nodes]
        if len(repos) < self._min_owner_repos:
            raise TruncatedSourceError(
                f"owner {owner}: {len(repos)} repositories visible, fewer than OPEN_PRS_FEED_MIN_OWNER_REPOS="
                f"{self._min_owner_repos}; check the gh login scopes, or lower the floor after archiving repositories"
            )
        out: list[OpenPr] = []
        for repo in repos:
            conn = repo.pullRequests
            if conn.totalCount > OWNER_PRS_PER_REPO and len(conn.nodes) == OWNER_PRS_PER_REPO:
                out.extend(self.open_prs(repo.nameWithOwner))
                continue
            if conn.totalCount != len(conn.nodes):
                raise TruncatedSourceError(
                    f"{repo.nameWithOwner} has {conn.totalCount} open PRs, the query returned {len(conn.nodes)}"
                )
            _unique(repo.nameWithOwner, conn.nodes)
            out.extend(_to_open_pr(repo.nameWithOwner, r) for r in conn.nodes)
        return out
