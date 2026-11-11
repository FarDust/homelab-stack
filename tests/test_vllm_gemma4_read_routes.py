"""Contract tests for the vLLM Gemma read routes.

Decision record: docs/adr/vllm_gemma4_read_routes_adr.md.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
STACK = ROOT / "stacks/llms/governance.yml"
HOST = "Host(`vllm-gemma4.${LOCAL_DOMAIN}`)"
READ = "traefik.http.routers.vllm-gemma4-read"
WAKE = "traefik.http.routers.vllm-gemma4"


def _labels() -> dict[str, str]:
    """Return the vllm-gemma4 service labels as a key/value map."""
    service = yaml.safe_load(STACK.read_text())["services"]["vllm-gemma4"]
    pairs = (label.split("=", 1) for label in service["deploy"]["labels"])
    return {key: value for key, value in pairs}


def test_read_router_matches_only_read_methods() -> None:
    """The read router matches GET and HEAD on the service host."""
    labels = _labels()
    assert labels[f"{READ}.rule"] == f"{HOST} && (Method(`GET`) || Method(`HEAD`))"
    assert labels[f"{READ}.service"] == "vllm-gemma4"


def test_read_router_never_wakes_the_engine() -> None:
    """The read router carries no Sablier middleware."""
    assert f"{READ}.middlewares" not in _labels()


def test_read_router_outranks_wake_router() -> None:
    """Reads hit the read router before the host-only wake router."""
    labels = _labels()
    assert int(labels[f"{READ}.priority"]) > int(labels[f"{WAKE}.priority"])


def test_wake_router_keeps_sablier_for_every_other_method() -> None:
    """Every other method still crosses the Sablier middleware."""
    labels = _labels()
    assert labels[f"{WAKE}.rule"] == HOST
    assert labels[f"{WAKE}.middlewares"] == "load-vllm@file"
    assert labels[f"{WAKE}.service"] == "vllm-gemma4"
    assert labels["sablier.group"] == "vllm-inference"


def test_both_routers_terminate_tls_on_websecure() -> None:
    """Both routers use the websecure entrypoint and the DNS resolver."""
    labels = _labels()
    for router in (READ, WAKE):
        assert labels[f"{router}.entrypoints"] == "websecure"
        assert labels[f"{router}.tls"] == "true"
        assert labels[f"{router}.tls.certresolver"] == "le-dns"
