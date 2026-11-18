"""Contract tests for the internal app-distribution origin.

Decision record: docs/adr/app_distribution_internal_adr.md.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
STACK = ROOT / "stacks/apps/dist.yml"
NGINX = ROOT / "stacks/apps/configs/apps-dist/nginx.conf"


def _service() -> dict:
    return yaml.safe_load(STACK.read_text())["services"]["web"]


def _labels() -> dict[str, str]:
    pairs = (label.split("=", 1) for label in _service()["deploy"]["labels"])
    return {key: value for key, value in pairs}


def test_stateful_placement_avoids_leader_and_ephemeral_nodes() -> None:
    constraints = _service()["deploy"]["placement"]["constraints"]
    assert "node.labels.storage.manager == true" in constraints
    assert "node.labels.swarm.leader != true" in constraints
    assert "node.labels.node.ephemeral != true" in constraints
    assert not any("node.hostname" in c for c in constraints)


def test_image_is_official_and_digest_pinned() -> None:
    image = _service()["image"]
    assert image.startswith("nginxinc/nginx-unprivileged:") and "@sha256:" in image


def test_hardened_runtime_without_published_ports() -> None:
    service = _service()
    assert service["read_only"] is True and service["cap_drop"] == ["ALL"]
    assert service["user"] == "101:101"
    assert "ports" not in service
    assert service["networks"] == ["traefik-public"]


def test_read_and_publish_hosts_are_separate_env_driven_routers() -> None:
    labels = _labels()
    assert labels["traefik.http.routers.apps-dist.rule"] == "Host(`${APPS_DIST_HOSTNAME?err}`)"
    assert labels["traefik.http.routers.apps-dist-publish.rule"] == "Host(`${APPS_DIST_PUBLISH_HOSTNAME?err}`)"
    assert labels["traefik.http.services.apps-dist.loadbalancer.server.port"] == "8080"
    assert labels["traefik.http.services.apps-dist-publish.loadbalancer.server.port"] == "8081"
    for router in ("apps-dist", "apps-dist-publish"):
        assert labels[f"traefik.http.routers.{router}.entrypoints"] == "websecure"
        assert labels[f"traefik.http.routers.{router}.tls.certresolver"] == "le-dns"


def test_publisher_secret_comes_from_the_private_directory() -> None:
    secrets = yaml.safe_load(STACK.read_text())["secrets"]
    assert secrets["publisher_htpasswd"]["file"] == "${APPS_DIST_PUBLISHER_HTPASSWD_FILE?err}"


def _server(port: int) -> str:
    text = NGINX.read_text()
    start = text.index(f"listen {port};")
    end = text.find("\n  server {", start)
    return text[start: end if end != -1 else len(text)]


def test_read_server_allows_only_get_and_head_and_no_dav() -> None:
    read = _server(8080)
    assert read.count("limit_except GET HEAD { deny all; }") == 2
    assert "dav_methods" not in read and "autoindex off;" in read
    assert "location / { return 404; }" in read


def test_publish_server_is_add_only_and_authenticated() -> None:
    publish = _server(8081)
    assert 'auth_basic "apps-dist publisher";' in publish
    assert "auth_basic_user_file /run/secrets/apps_dist_publisher_htpasswd;" in publish
    assert "dav_methods PUT;" in publish
    assert publish.count("limit_except GET HEAD PUT { deny all; }") == 2
    assert "DELETE" not in publish and "MOVE" not in publish


def test_request_temp_files_share_the_data_volume() -> None:
    assert "client_body_temp_path /var/cache/nginx/tmp/client" in NGINX.read_text()
    volumes = _service()["volumes"]
    assert "apps_dist_data:/var/cache/nginx" in volumes


def test_publish_server_refuses_to_overwrite_an_apk() -> None:
    publish = _server(8081)
    block = publish[publish.index(r'location ~ "\.apk$"'):]
    assert 'if (-f $request_filename) { set $apk_put "exists"; }' in block
    assert 'if ($apk_put = "exists-put") { return 409; }' in block


def test_apk_cache_policy_applies_only_to_successful_responses() -> None:
    read = _server(8080)
    assert "add_header Cache-Control 'private, max-age=31536000, immutable';" in read
    assert "immutable' always" not in read


def test_mutable_index_files_carry_no_weak_validator() -> None:
    read = _server(8080)
    index_block = read[read.index('location ~ "^/(repo|archive)/" {'):]
    assert "etag off;" in index_block and "if_modified_since off;" in index_block


def test_no_plain_environment_secrets() -> None:
    assert "environment" not in _service()
