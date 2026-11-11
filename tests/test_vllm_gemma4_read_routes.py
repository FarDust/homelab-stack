"""Contract tests for the vLLM Gemma read routes, model list and readiness.

Decision record: docs/adr/vllm_gemma4_read_routes_adr.md.
"""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
STACK = ROOT / "stacks/llms/governance.yml"
TRAEFIK = ROOT / "stacks/main/configs/traefik/static_conf.yml"
CATALOGUE = ROOT / "stacks/llms/configs/vllm/models-nginx.conf"
HOST = "Host(`vllm-gemma4.${LOCAL_DOMAIN}`)"
READ = "traefik.http.routers.vllm-gemma4-read"
WAKE = "traefik.http.routers.vllm-gemma4"
MODELS = "traefik.http.routers.vllm-gemma4-models"


def _stack() -> dict:
    """Return the parsed governance stack."""
    return yaml.safe_load(STACK.read_text())


def _service_labels(name: str) -> dict[str, str]:
    """Return a service's deploy labels as a key/value map."""
    service = _stack()["services"][name]
    pairs = (label.split("=", 1) for label in service["deploy"]["labels"])
    return {key: value for key, value in pairs}


def _labels() -> dict[str, str]:
    """Return the vllm-gemma4 service labels as a key/value map."""
    return _service_labels("vllm-gemma4")


def _seconds(duration: str) -> int:
    """Convert a compose or Go duration such as 14m, 900s or 1h30m to seconds."""
    parts = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", duration)
    assert parts and any(parts.groups()), f"unparseable duration {duration!r}"
    hours, minutes, seconds = (int(value or 0) for value in parts.groups())
    return hours * 3600 + minutes * 60 + seconds


def _engine_arg(flag: str) -> str:
    """Return the value that follows a flag in the vllm-gemma4 command."""
    command = _stack()["services"]["vllm-gemma4"]["command"]
    assert flag in command, f"vllm-gemma4 command lacks {flag}"
    return str(command[command.index(flag) + 1])


def _catalogue_body(location: str) -> dict:
    """Return the JSON body nginx returns for an exact location."""
    text = CATALOGUE.read_text()
    marker = f"location = {location} {{"
    assert marker in text, f"{CATALOGUE.name} has no exact location {location}; keep it in step with the engine"
    block = text[text.index(marker) :]
    body = block[block.index("return 200 '") + len("return 200 '") : block.index("';")]
    return json.loads(body)


def _wake_middleware() -> dict:
    """Return the Sablier middleware the wake router uses."""
    middleware = _labels()[f"{WAKE}.middlewares"].removesuffix("@file")
    return yaml.safe_load(TRAEFIK.read_text())["http"]["middlewares"][middleware]["plugin"]["sablier"]


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
    assert _wake_middleware()["group"] == "vllm-inference"


def test_both_routers_terminate_tls_on_websecure() -> None:
    """Both routers use the websecure entrypoint and the DNS resolver."""
    labels = _labels()
    for router in (READ, WAKE):
        assert labels[f"{router}.entrypoints"] == "websecure"
        assert labels[f"{router}.tls"] == "true"
        assert labels[f"{router}.tls.certresolver"] == "le-dns"


def test_catalogue_lists_the_served_model() -> None:
    """The static list names the model the engine serves, with its context length."""
    listing = _catalogue_body("/v1/models")
    assert listing["object"] == "list"
    (model,) = listing["data"]
    assert model["id"] == _engine_arg("--served-model-name")
    assert model["root"] == _engine_arg("--model")
    assert model["max_model_len"] == int(_engine_arg("--max-model-len"))
    assert _catalogue_body(f"/v1/models/{model['id']}") == model
    assert _catalogue_body("/v1/models/") == listing


def test_models_router_outranks_read_router_without_waking() -> None:
    """Model listing is answered by the catalogue before the read and wake routers."""
    models = _service_labels("vllm-gemma4-models")
    assert models[f"{MODELS}.rule"] == (
        f"{HOST} && (Method(`GET`) || Method(`HEAD`)) && "
        "(Path(`/v1/models`) || PathPrefix(`/v1/models/`))"
    )
    assert int(models[f"{MODELS}.priority"]) > int(_labels()[f"{READ}.priority"])
    assert models[f"{MODELS}.service"] == "vllm-gemma4-models"
    assert f"{MODELS}.middlewares" not in models
    assert models[f"{MODELS}.entrypoints"] == "websecure"
    assert models[f"{MODELS}.tls.certresolver"] == "le-dns"


def test_catalogue_is_always_on() -> None:
    """The catalogue stays out of Sablier and off ephemeral nodes."""
    service = _stack()["services"]["vllm-gemma4-models"]
    assert not any(key.startswith("sablier.") for key in _service_labels("vllm-gemma4-models"))
    assert "node.labels.node.ephemeral != true" in service["deploy"]["placement"]["constraints"]
    assert service["deploy"]["replicas"] == 1


def test_engine_readiness_fits_the_sablier_window() -> None:
    """The engine probes /health and its grace period ends before Sablier gives up on the request."""
    check = _stack()["services"]["vllm-gemma4"]["healthcheck"]
    assert "http://127.0.0.1:8000/health" in check["test"]
    sablier = _wake_middleware()
    window = min(_seconds(sablier["blocking"]["timeout"]), _seconds(sablier["sessionDuration"]))
    assert _seconds(check["start_period"]) < window
