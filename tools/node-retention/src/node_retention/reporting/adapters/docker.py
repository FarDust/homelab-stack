"""One bounded batch observation of running containers; no mutation commands."""

from __future__ import annotations

import subprocess
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from node_retention.reporting.domain.models import Container, ReportError
from node_retention.reporting.domain.ports import Budget

_FORMAT = (
    '{"name":{{json .Name}},"owner":{{json (index .Config.Labels "jra-who")}},'
    '"created":{{json .Created}},"mounts":{{json .Mounts}}}'
)


class MountObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    Type: Literal["bind", "volume", "tmpfs"]
    Source: str | None = None  # Docker tmpfs has no host source by contract.

    @model_validator(mode="after")
    def host_source(self) -> MountObservation:
        if self.Type != "tmpfs" and (self.Source is None or not self.Source.startswith("/")):
            raise ValueError("bind/volume mount requires an absolute host source")
        return self


class ContainerObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    owner: str | None
    created: AwareDatetime
    mounts: list[MountObservation]


class DockerSnapshot:
    def __init__(self, executable: str = "docker") -> None:
        self.executable = executable

    def _call(self, arguments: list[str], budget: Budget) -> str:
        try:
            remaining = min(1.0, budget.remaining())
            result = subprocess.run(
                ["/usr/bin/timeout", "--signal=KILL", str(remaining), self.executable, *arguments],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ReportError("running container observation failed or exceeded report budget") from error
        return result.stdout

    def snapshot(self, budget: Budget) -> tuple[Container, ...]:
        ids = self._call(["ps", "-q"], budget).split()
        if not ids:
            return ()
        rows = self._call(["inspect", "--format", _FORMAT, *ids], budget).splitlines()
        found = []
        try:
            for line in rows:
                budget.remaining()
                row = ContainerObservation.model_validate_json(line)
                mounts = tuple(
                    mount.Source for mount in row.mounts if mount.Type != "tmpfs" and mount.Source is not None
                )
                found.append(Container(row.name.lstrip("/"), row.owner or None, row.created.timestamp(), mounts))
        except (ValidationError, ValueError, TypeError) as error:
            raise ReportError("container metadata is missing or malformed") from error
        if len(found) != len(ids):
            raise ReportError("running container inventory changed; report completeness is unknown")
        return tuple(found)
