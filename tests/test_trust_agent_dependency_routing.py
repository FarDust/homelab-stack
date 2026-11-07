from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
TRAEFIK_STACK = ROOT / "stacks/main/traefik.yml"
TRUST_STACK = ROOT / "stacks/main/trust-agent.yml"
IDENTITY_STACK = ROOT / "stacks/main/identity.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_traefik_publishes_exact_dependency_aliases_on_trust_overlay() -> None:
    traefik = _load(TRAEFIK_STACK)["services"]["traefik"]
    networks = traefik["networks"]

    assert traefik["image"] == (
        "traefik:latest@sha256:"
        "6b9cbca6fac42ab0075f5437d8dc1685cfd188626d8d515839ea94f8b6271c42"
    )
    assert networks["trust-internal"]["aliases"] == [
        "vault.${LOCAL_DOMAIN?err}",
        "idp.${LOCAL_DOMAIN?err}",
    ]
    assert networks["traefik"] is None
    assert networks["traefik-public"] is None


def test_dependency_aliases_do_not_widen_service_networks() -> None:
    trust_networks = _load(TRUST_STACK)["services"]["trust-agent"]["networks"]
    identity = _load(IDENTITY_STACK)["services"]

    assert trust_networks == ["trust-internal"]
    assert identity["vault"]["networks"] == ["traefik-public"]
    assert set(identity["keycloak"]["networks"]) == {
        "keycloak-internal",
        "traefik-public",
    }
