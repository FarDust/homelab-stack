"""Docker adapter through the `docker` CLI. Only images and build cache are pruned; volumes are never touched."""

from __future__ import annotations

import json
import re
import subprocess

from node_retention.domain.errors import ImageLookupError
from node_retention.domain.rules import IMAGE_ID

_UNITS = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3}
_SIZE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[KMGT]?i?B)", re.IGNORECASE)

_FORBIDDEN_LONG_FLAGS = frozenset({"--all", "--volumes"})
_SHORT_FLAGS = re.compile(r"^-[A-Za-z]+(?:=.*)?$")


def forbidden_prune_flag(args: tuple[str, ...]) -> str | None:
    """The first argument that widens a prune beyond dangling images and aged build cache, or None.

    Applies to every argument list that contains `prune` (image, builder, system, container, volume, network):
    `--all` and `--volumes` with or without `=value`, and any short-flag cluster that contains `a` (`-a`, `-af`,
    `-fa`, `-a=true`). A flag value such as `until=24h` does not start with a dash and is not inspected.
    """
    if "prune" not in args:
        return None
    for arg in args:
        if arg.split("=", 1)[0] in _FORBIDDEN_LONG_FLAGS:
            return arg
        if _SHORT_FLAGS.match(arg) and "a" in arg.split("=", 1)[0][1:].lower():
            return arg
    return None


def parse_size(text: str) -> int:
    """Parse a Docker human size such as `6.298GB` or `0B`; raises ValueError when there is none."""
    match = _SIZE.search(text)
    if match is None:
        raise ValueError(f"no size in {text!r}")
    return int(float(match.group("num")) * _UNITS[match.group("unit").upper()])


class DockerCli:
    def __init__(self, helper_image: str, binary: str = "docker", timeout_s: float = 600.0) -> None:
        self._image = helper_image
        self._bin = binary
        self._timeout = timeout_s

    def _run(self, *args: str) -> str:
        # Pruning is limited to dangling images and aged build cache; `-a/--all` would also remove every unused
        # tagged image, and `--volumes` named data. Refuse them whatever the caller passes.
        flag = forbidden_prune_flag(args)
        if flag is not None:
            raise ValueError(
                f"refusing a prune with {flag!r}: only dangling images and aged build cache may go: {args!r}"
            )
        done = subprocess.run([self._bin, *args], capture_output=True, text=True, timeout=self._timeout, check=True)
        return done.stdout

    def mount_sources(self) -> set[str]:
        ids = self._run("ps", "-aq").split()
        if not ids:
            return set()
        out = self._run("inspect", "--format", '{{range .Mounts}}{{.Source}}{{"\\n"}}{{end}}', *ids)
        return {line for line in out.splitlines() if line.startswith("/")}

    def dangling_images_reclaimable(self) -> int:
        ids = self._run("image", "ls", "--filter", "dangling=true", "--quiet").split()
        if not ids:
            return 0
        out = self._run("image", "inspect", "--format", "{{.Size}}", *ids)
        return sum(int(line) for line in out.split())

    def build_cache_reclaimable(self) -> int:
        for line in self._run("system", "df", "--format", "{{json .}}").splitlines():
            row = json.loads(line)
            if row["Type"] == "Build Cache":
                return parse_size(row["Reclaimable"])
        raise RuntimeError("docker system df reported no Build Cache row")

    def image_id(self, ref: str) -> str | None:
        done = subprocess.run(
            [self._bin, "image", "inspect", "--format", "{{.Id}}", ref],
            capture_output=True,
            text=True,
            timeout=self._timeout,
            check=False,
        )
        if done.returncode == 0:
            observed = done.stdout.strip()
            if not IMAGE_ID.match(observed):
                raise ImageLookupError(f"docker image inspect {ref!r} returned {observed!r}, not a sha256 image id")
            return observed
        if "no such image" in done.stderr.lower():
            return None
        raise ImageLookupError(f"docker image inspect {ref!r} failed ({done.returncode}): {done.stderr.strip()[-200:]}")

    def prune_dangling_images(self) -> int:
        return self._reclaimed(self._run("image", "prune", "--force"))

    def remove_path_as_root(self, path: str) -> None:
        """Remove one path (tree) with a helper container that mounts only its parent directory."""
        parent, _, name = path.rstrip("/").rpartition("/")
        if not parent or not name or name in {".", ".."}:
            raise ValueError(f"refusing to remove {path!r} as root")
        self._run("run", "--rm", "--network", "none", "-v", f"{parent}:/p", self._image, "rm", "-rf", f"/p/{name}")

    def prune_build_cache(self, older_than_hours: int) -> int:
        return self._reclaimed(self._run("builder", "prune", "--force", "--filter", f"until={older_than_hours}h"))

    @staticmethod
    def _reclaimed(output: str) -> int:
        match = re.search(r"Total(?: reclaimed space)?:\s*(.+)", output)
        if match is None:
            raise RuntimeError(f"docker prune printed no reclaimed total: {output[-200:]!r}")
        return parse_size(match.group(1))
