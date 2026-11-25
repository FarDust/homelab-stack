"""Collect a complete snapshot, then publish it; as decided in docs/adr/open_prs_feed_adr.md."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from open_prs_feed.domain.errors import EmptySnapshotError
from open_prs_feed.domain.models import OpenPr, Snapshot
from open_prs_feed.domain.ports import AtomicSink, Clock, PullRequestSource


@dataclass(frozen=True)
class PublishResult:
    snapshot: Snapshot
    numbers_target: str
    detail_target: str


class CollectSnapshot:
    def __init__(
        self,
        source: PullRequestSource,
        clock: Clock,
        repos: Sequence[str],
        allow_empty: bool,
        owners: Sequence[str] = (),
    ) -> None:
        if not repos and not owners:
            raise ValueError("at least one repository or owner is required")
        self._source = source
        self._clock = clock
        self._repos = tuple(repos)
        self._owners = tuple(owners)
        self._allow_empty = allow_empty

    def __call__(self) -> Snapshot:
        """Every repository and owner must answer; the first failure propagates and no snapshot exists."""
        found: dict[tuple[str, int], OpenPr] = {}
        for owner in self._owners:
            for pr in self._source.open_prs_of_owner(owner):
                found[(pr.repo, pr.number)] = pr
        for repo in self._repos:
            for pr in self._source.open_prs(repo):
                found[(pr.repo, pr.number)] = pr
        if not found and not self._allow_empty:
            raise EmptySnapshotError(
                f"no open PR in {len(self._repos)} repositories and {len(self._owners)} owners; refusing to publish "
                "an empty list (set OPEN_PRS_FEED_ALLOW_EMPTY=true when that is the real state)"
            )
        prs = sorted(found.values(), key=lambda p: (p.repo, p.number))
        return Snapshot(generated_at=self._clock.now(), owners=self._owners, repos=self._repos, prs=tuple(prs))


class PublishOpenPrs:
    """Detail file first, consumer file last: a failure leaves the consumer's last good file untouched."""

    def __init__(self, collect: CollectSnapshot, sink: AtomicSink, numbers_name: str, detail_name: str) -> None:
        self._collect = collect
        self._sink = sink
        self._numbers_name = numbers_name
        self._detail_name = detail_name

    def __call__(self) -> PublishResult:
        snap = self._collect()
        self._sink.write(self._detail_name, snap.render_detail())
        self._sink.write(self._numbers_name, snap.render_numbers())
        return PublishResult(
            snapshot=snap,
            numbers_target=self._sink.describe(self._numbers_name),
            detail_target=self._sink.describe(self._detail_name),
        )
