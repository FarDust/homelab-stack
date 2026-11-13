"""Contract tests for the cluster feature-flag service stack.

Decision record: docs/adr/feature_flags_service_adr.md.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
STACK = ROOT / "stacks/main/feature-flags.yml"
ADR = ROOT / "docs/adr/feature_flags_service_adr.md"
CONTRACT = ROOT / "config/env-contract.yaml"
PROMETHEUS = ROOT / "stacks/main/configs/prometheus/prometheus.yml"


def _service() -> dict:
    return yaml.safe_load(STACK.read_text())["services"]["unleash"]


def _labels() -> list[str]:
    return _service()["deploy"]["labels"]


def test_two_replicas_on_distinct_stable_nodes_by_label() -> None:
    deploy = _service()["deploy"]
    assert deploy["replicas"] == 2
    placement = deploy["placement"]
    assert placement["max_replicas_per_node"] == 1
    assert "node.labels.node.ephemeral != true" in placement["constraints"]
    assert not any("node.hostname" in constraint for constraint in placement["constraints"]), "place by labels"


def test_image_comes_from_the_pinned_env_variable() -> None:
    assert _service()["image"] == "${FLAGS_UNLEASH_IMAGE?err}"
    contract = yaml.safe_load(CONTRACT.read_text())["variables"]
    names = {variable["name"] for variable in contract}
    assert {"FLAGS_UNLEASH_IMAGE", "FLAGS_FRONTEND_HOSTNAME", "FLAGS_FRONTEND_TOKEN_HEADER", "FLAGS_DATABASE_SSL"} <= names


def test_health_resources_and_rollback() -> None:
    service = _service()
    assert "/health" in " ".join(service["healthcheck"]["test"])
    limits = service["deploy"]["resources"]["limits"]
    assert limits["memory"] == "512M" and limits["cpus"] == "0.5"
    assert service["deploy"]["update_config"]["failure_action"] == "rollback"
    # start-first deadlocks with max_replicas_per_node 1 on two eligible nodes (seen live 2026-11-13)
    assert service["deploy"]["update_config"]["order"] == "stop-first"
    assert service["deploy"]["update_config"]["parallelism"] == 1


def test_secrets_are_files_not_environment() -> None:
    service = _service()
    environment = service["environment"]
    assert environment["DATABASE_URL_FILE"] == "/run/secrets/feature_flags_db_url"
    assert "DATABASE_URL" not in environment and "UNLEASH_DEFAULT_ADMIN_PASSWORD" not in environment
    assert {secret["source"] for secret in service["secrets"]} == {"feature_flags_db_url", "feature_flags_admin_password"}
    assert environment["SEND_TELEMETRY"] == "false"


def test_admin_ui_is_behind_keycloak_and_token_api_requires_a_token() -> None:
    labels = _labels()
    ui = next(label for label in labels if label.startswith("traefik.http.routers.feature-flags.middlewares="))
    assert "feature-flags-oauth2-forward-auth@swarm" in ui
    api_rule = next(label for label in labels if label.startswith("traefik.http.routers.feature-flags-api.rule="))
    assert "HeaderRegexp(`Authorization`, `.+`)" in api_rule
    assert "/api/admin" in api_rule and "/api/client" in api_rule
    frontend_rule = next(label for label in labels if label.startswith("traefik.http.routers.feature-flags-frontend.rule="))
    assert "PathPrefix(`/flags/api/frontend`)" in frontend_rule
    assert any(label.startswith("traefik.http.middlewares.feature-flags-frontend-token.headers.customrequestheaders.Authorization=") for label in labels)
    assert all("DOMAIN_NAME" not in label for label in labels), "tailnet only: LOCAL_DOMAIN, never the public domain"


def test_prometheus_scrapes_both_replicas() -> None:
    jobs = yaml.safe_load(PROMETHEUS.read_text())["scrape_configs"]
    job = next(job for job in jobs if job["job_name"] == "feature-flags")
    assert job["metrics_path"] == "/internal-backstage/prometheus"
    assert job["dns_sd_configs"][0]["names"] == ["tasks.main-feature-flags_unleash"]


def test_adr_states_limits_failure_tests_and_rollback() -> None:
    text = ADR.read_text()
    for heading in ("## Context", "## Decision", "## Alternatives", "## Consequences", "## Verification", "## Rollback"):
        assert heading in text, f"ADR is missing {heading!r}"
    assert "What \"never fails\" means" in text
    assert "flags-breakglass" in text
