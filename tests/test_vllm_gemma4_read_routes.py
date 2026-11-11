"""Contract tests for the vLLM Gemma read routes.

Decision record: docs/adr/vllm_gemma4_read_routes_adr.md.
"""

import json
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


CATALOGUE = ROOT / "stacks/llms/configs/vllm/models-nginx.conf"
MODELS = "traefik.http.routers.vllm-gemma4-models"


def _stack() -> dict:
    """Return the parsed governance stack."""
    return yaml.safe_load(STACK.read_text())


def _engine_arg(flag: str) -> str:
    """Return the value that follows a flag in the vllm-gemma4 command."""
    command = _stack()["services"]["vllm-gemma4"]["command"]
    return str(command[command.index(flag) + 1])


def _catalogue_body(location: str) -> dict:
    """Return the JSON body nginx returns for an exact location."""
    text = CATALOGUE.read_text()
    marker = f"location = {location} {{"
    block = text[text.index(marker) :]
    body = block[block.index("return 200 '") + len("return 200 '") : block.index("';")]
    return json.loads(body)


def _model_labels() -> dict[str, str]:
    """Return the vllm-gemma4-models service labels as a key/value map."""
    service = _stack()["services"]["vllm-gemma4-models"]
    pairs = (label.split("=", 1) for label in service["deploy"]["labels"])
    return {key: value for key, value in pairs}


def test_catalogue_lists_the_served_model() -> None:
    """The static list names the model the engine serves, with its context length."""
    listing = _catalogue_body("/v1/models")
    assert listing["object"] == "list"
    (model,) = listing["data"]
    assert model["id"] == _engine_arg("--served-model-name")
    assert model["root"] == _engine_arg("--model")
    assert model["max_model_len"] == int(_engine_arg("--max-model-len"))
    assert _catalogue_body(f"/v1/models/{model['id']}") == model


def test_models_router_outranks_read_router_without_waking() -> None:
    """Model listing is answered by the catalogue before the read and wake routers."""
    models = _model_labels()
    engine = _labels()
    assert models[f"{MODELS}.rule"] == (
        f"{HOST} && (Method(`GET`) || Method(`HEAD`)) && "
        "(Path(`/v1/models`) || PathPrefix(`/v1/models/`))"
    )
    assert int(models[f"{MODELS}.priority"]) > int(engine[f"{READ}.priority"])
    assert models[f"{MODELS}.service"] == "vllm-gemma4-models"
    assert f"{MODELS}.middlewares" not in models
    assert models[f"{MODELS}.entrypoints"] == "websecure"
    assert models[f"{MODELS}.tls.certresolver"] == "le-dns"


def test_catalogue_runs_on_stable_nodes() -> None:
    """The catalogue stays off ephemeral nodes so the list answers when the GPU node is down."""
    service = _stack()["services"]["vllm-gemma4-models"]
    assert "node.labels.node.ephemeral != true" in service["deploy"]["placement"]["constraints"]
    assert service["deploy"]["replicas"] == 1


def test_engine_is_ready_only_when_it_serves() -> None:
    """The engine healthcheck probes /health and leaves room for the model load."""
    check = _stack()["services"]["vllm-gemma4"]["healthcheck"]
    assert "http://127.0.0.1:8000/health" in check["test"]
    minutes = int(check["start_period"].removesuffix("m"))
    assert minutes >= 15


def test_engine_offloads_without_uva() -> None:
    """CPU offload uses vLLM's copy path, because UVA views of unpinned memory fail on WSL."""
    environment = _stack()["services"]["vllm-gemma4"]["environment"]
    assert "--cpu-offload-gb" in _stack()["services"]["vllm-gemma4"]["command"]
    assert "VLLM_WEIGHT_OFFLOADING_DISABLE_UVA=1" in environment
