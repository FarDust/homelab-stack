"""Staggered start of the GPU services on the ephemeral node.

As decided in docs/adr/gpu_node_staggered_start_adr.md
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

# service -> (stack file, slot seconds after VM boot, restart delay seconds), lightest first.
PLAN = {
    "whisper": ("stacks/llms/speech-gpu.yml", 120, 30),
    "ollama": ("stacks/llms/governance.yml", 180, 45),
    "jellyfin": ("stacks/hobby/streaming.yml", 240, 60),
    "jellyseerr": ("stacks/hobby/streaming.yml", 290, 75),
    "sonarr": ("stacks/hobby/streaming.yml", 340, 90),
    "radarr": ("stacks/hobby/streaming.yml", 390, 105),
    "bazarr": ("stacks/hobby/streaming.yml", 440, 120),
    "qbittorrent": ("stacks/hobby/streaming.yml", 490, 135),
    "jupyter-tensorflow": ("stacks/devtools/notebooks.yml", 560, 150),
    "comfy-gpu": ("stacks/vision/generation.yml", 660, 165),
}
MIN_SPACING_S = 45


def _service(name: str) -> dict:
    """Return the parsed compose service for a planned name."""
    stack = yaml.safe_load((ROOT / PLAN[name][0]).read_text(encoding="utf-8"))
    return stack["services"][name]


def _env(service: dict) -> dict[str, str]:
    """Return the service environment as a mapping."""
    env = service["environment"]
    if isinstance(env, dict):
        return {k: str(v) for k, v in env.items()}
    return dict(item.split("=", 1) for item in env)


def _seconds(value: str) -> int:
    """Parse a whole-second compose duration such as 300s."""
    return int(value.removesuffix("s"))


@pytest.mark.parametrize("name", sorted(PLAN))
def test_each_gpu_service_declares_its_slot_and_ordered_restart_delay(name: str) -> None:
    """Each planned service declares its slot, gate entrypoint and restart delay."""
    _, slot, delay = PLAN[name]
    service = _service(name)
    assert _env(service)["STARTUP_GATE_SLOT_S"] == str(slot)
    assert service["entrypoint"][:2] == ["sh", "-c"]
    assert service["entrypoint"][-1] == "startup-gate"
    assert "/proc/uptime" in service["entrypoint"][2]
    restart = service["deploy"]["restart_policy"]
    assert restart["condition"] in {"any", "on-failure"}
    raw = restart["delay"]
    parsed = int(raw.removesuffix("s")) if raw.endswith("s") else None
    assert parsed == delay, f"{name} restart delay {raw}"


def test_slots_and_restart_delays_are_strictly_ordered_and_spaced() -> None:
    """Slots and restart delays increase with the rank and keep the minimum spacing."""
    ordered = list(PLAN.values())
    slots = [slot for _, slot, _ in ordered]
    delays = [delay for _, _, delay in ordered]
    assert slots == sorted(set(slots))
    assert delays == sorted(set(delays))
    assert all(b - a >= MIN_SPACING_S for a, b in zip(slots, slots[1:], strict=False))


def test_models_with_a_healthcheck_cover_the_gate_wait_and_model_load() -> None:
    """The whisper start period covers the gate wait plus the model load."""
    whisper = _service("whisper")
    assert _seconds(whisper["healthcheck"]["start_period"]) >= 300


def test_vllm_gemma4_stays_declared_at_zero_replicas() -> None:
    """The disabled vLLM service is neither scaled nor gated by this change."""
    governance = yaml.safe_load((ROOT / "stacks/llms/governance.yml").read_text(encoding="utf-8"))
    vllm = governance["services"]["vllm-gemma4"]
    assert vllm["deploy"]["replicas"] == 0
    assert "entrypoint" not in vllm


def _run_gate(
    tmp_path: Path, name: str, uptime: str, args: list[str]
) -> tuple[str, list[str]]:
    """Run one service's own gate script with a fake uptime file and a fake sleep."""
    slot = PLAN[name][1]
    script = _service(name)["entrypoint"][2]
    # Compose escapes dollar signs as $$; the container shell receives single dollars.
    script = script.replace("$$", "$")
    script, replaced = re.subn(r'^exec .* "\$@"$', 'exec echo ran "$@"', script, flags=re.M)
    assert replaced == 1, f"{name} gate must end by exec-ing the original entrypoint"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "sleep.log"
    sleeper = fake_bin / "sleep"
    sleeper.write_text(f'#!/bin/sh\necho "$1" >> "{log}"\n', encoding="utf-8")
    sleeper.chmod(sleeper.stat().st_mode | stat.S_IXUSR)
    uptime_file = tmp_path / "uptime"
    uptime_file.write_text(f"{uptime} 0.00\n", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "STARTUP_GATE_UPTIME_FILE": str(uptime_file),
        "STARTUP_GATE_SLOT_S": str(slot),
    }
    done = subprocess.run(
        ["sh", "-c", script, "startup-gate", *args],
        env=env, capture_output=True, text=True, check=True,
    )
    sleeps = log.read_text(encoding="utf-8").split() if log.exists() else []
    return done.stdout, sleeps


@pytest.mark.skipif(os.name == "nt", reason="POSIX sh gate script")
@pytest.mark.parametrize("name", sorted(PLAN))
def test_gate_waits_only_for_the_remaining_boot_time(tmp_path: Path, name: str) -> None:
    """Each gate sleeps for slot minus uptime and passes its arguments through."""
    remaining = PLAN[name][1] - 100
    out, sleeps = _run_gate(tmp_path, name, "100.50", ["--flag", "value"])
    assert sleeps == [str(remaining)]
    assert f"waiting {remaining}s" in out
    assert out.rstrip().endswith("ran --flag value")


@pytest.mark.skipif(os.name == "nt", reason="POSIX sh gate script")
@pytest.mark.parametrize("name", sorted(PLAN))
def test_gate_is_a_no_op_after_the_slot_has_passed(tmp_path: Path, name: str) -> None:
    """After the slot a routine restart does not wait."""
    out, sleeps = _run_gate(tmp_path, name, "351137.72", [])
    assert sleeps == []
    assert re.fullmatch(r"ran\s*", out)
