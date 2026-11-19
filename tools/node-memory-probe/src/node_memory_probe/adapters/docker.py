"""Docker CLI adapters: container names for cgroup ids and read-only jcmd through `docker exec`."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from node_memory_probe.domain.models import ProcessBrief
from node_memory_probe.domain.ports import ContainerDirectoryError, JcmdError

# jcmd starts a small JVM of its own inside the target's container; keep it small and short-lived.
JCMD_JVM_OPTIONS = ("-J-Xms8m", "-J-Xmx64m", "-J-XX:+UseSerialGC", "-J-XX:TieredStopAtLevel=1")


class DockerError(ContainerDirectoryError):
    """docker answered with an error that is not "no such container"."""


class DockerCli:
    def __init__(self, docker_bin: str, timeout_s: float) -> None:
        self._bin = docker_bin
        self._timeout = timeout_s

    def _inspect(self, refs: Sequence[str], template: str) -> list[str]:
        try:
            proc = subprocess.run(
                [self._bin, "inspect", "--type", "container", "--format", template, *refs],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerError(f"docker inspect timed out after {self._timeout:.0f} s") from exc
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        # Exit 1 with "No such container" for refs that exited meanwhile; the others are still printed.
        unexpected = [e for e in proc.stderr.splitlines() if e.strip() and "No such" not in e]
        if proc.returncode != 0 and unexpected:
            raise DockerError(f"docker inspect failed: {unexpected[-1][:200]}")
        return lines

    def names(self, container_ids: Sequence[str]) -> dict[str, str]:
        """Swarm service name when the container is a task, else the container name."""
        out: dict[str, str] = {}
        template = '{{.Id}}|{{.Name}}|{{index .Config.Labels "com.docker.swarm.service.name"}}'
        for line in self._inspect(container_ids, template):
            cid, name, service = line.split("|", 2)
            out[cid] = service or name.lstrip("/")
        return out

    def resolve(self, names: Sequence[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self._inspect(names, "{{.Name}}|{{.Id}}|{{.State.Running}}"):
            name, cid, running = line.split("|", 2)
            if running == "true":
                out[name.lstrip("/")] = cid
        return out


class NoJcmd:
    """jcmd switched off by configuration: every call fails, so the heap comes from the JVM flags."""

    def run(self, brief: ProcessBrief, command: str) -> str:
        raise JcmdError("jcmd disabled by NODE_MEMORY_PROBE_JCMD_ENABLED=false")


class DockerJcmd:
    """`docker exec -u <uid>:<gid> <container> jcmd <ns-pid> <command>`: the attach needs the JVM's own ids."""

    def __init__(self, docker_bin: str, timeout_s: float) -> None:
        self._bin = docker_bin
        self._timeout = timeout_s

    def run(self, brief: ProcessBrief, command: str) -> str:
        if brief.container_id is None:
            raise JcmdError(f"pid {brief.pid} is not in a container; host JVMs are read from their flags")
        argv = [
            self._bin,
            "exec",
            "-u",
            f"{brief.uid}:{brief.gid}",
            brief.container_id,
            "jcmd",
            *JCMD_JVM_OPTIONS,
            str(brief.ns_pid),
            command,
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=self._timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise JcmdError(f"{command} timed out after {self._timeout:.0f} s") from exc
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
            raise JcmdError(f"{command} exit {proc.returncode}: {tail[0][:200]}")
        return proc.stdout
