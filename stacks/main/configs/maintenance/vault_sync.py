"""Lightweight cluster-vault -> Neo4j/Marquez sync loop.

Scope: the fardustdev compose vault only (bind-mounted locally into this
container). The personal Windows-side vault is a separate, not-yet-bridged
half of "vault interoperability" -- out of scope here, see the vault note
vault-interoperability-sync-manifest for why.

Env vars:
  VAULT_ROOT            default /vault
  SYNC_INTERVAL_SECONDS default 1800 (30 min)
  NEO4J_URI             default bolt://devtools-ontology_neo4j:7687
  NEO4J_USER            default neo4j
  NEO4J_PASSWORD_FILE   default /run/secrets/neo4j_ontology_auth_password (format user/pass)
  LITELLM_BASE_URL      default http://litellm.llms-governance:4000  (internal)
  LITELLM_API_KEY_FILE  default /run/secrets/litellm_api_key
  LITELLM_MODEL         default gpt-5-mini
  MARQUEZ_URL           default http://marquez.devtools-lineage:5000
  DRY_RUN               default "true" -- when true, logs proposed Cypher/lineage
                         instead of applying them. Must be explicitly set to
                         "false" to write.
"""
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from neo4j import GraphDatabase

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", "/vault"))
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "1800"))
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://devtools-ontology_neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD_FILE = os.environ.get("NEO4J_PASSWORD_FILE", "/run/secrets/neo4j_ontology_auth_password")
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://litellm.llms-governance:4000")
LITELLM_API_KEY_FILE = os.environ.get("LITELLM_API_KEY_FILE", "/run/secrets/litellm_api_key")
LITELLM_MODEL = os.environ.get("LITELLM_MODEL", "gpt-5-mini")
MARQUEZ_URL = os.environ.get("MARQUEZ_URL", "http://marquez.devtools-lineage:5000")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"

MANIFEST_PATH = VAULT_ROOT / ".sync-manifest.tsv"

KNOWN_CLASSES = [
    "Node", "Service", "ExternalService", "Topic", "Stack", "Concern",
    "Policy", "Cluster", "Agent", "Vault", "VPNProvider", "NetworkProtocol",
    "Report", "Project",
]

EXTRACTION_SYSTEM_PROMPT = f"""You extract real entities and relationships from one cluster
documentation file for a Neo4j ontology. Only extract what the text actually
states -- never invent facts, relationships, or entities not supported by
the content. Reuse these existing entity classes where they fit: {", ".join(KNOWN_CLASSES)}.
If the file doesn't describe a distinct entity/relationship (e.g. it's pure
navigation, boilerplate, or badges), return empty lists. Keep entity names
exactly as they appear for known products/services so they match existing
graph nodes (e.g. 'PostgreSQL', not 'postgres' or 'Postgres DB').

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{
  "entities": [
    {{"class": "<one of: {", ".join(KNOWN_CLASSES)}>", "name": "<exact name>",
     "properties": {{"<key>": "<short string value>", ...}} }}
  ],
  "relationships": [
    {{"from_name": "<entity name>", "type": "<RELATIONSHIP_TYPE_UPPER_SNAKE_CASE>", "to_name": "<entity name>"}}
  ]
}}
Both lists may be empty. Keep "properties" to a handful of short, factual
key/value pairs (e.g. purpose, image, endpoint) -- not full prose."""


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def compute_hashes(root: Path) -> dict:
    hashes = {}
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root).as_posix()
        hashes[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return hashes


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        h, rel = line.split("\t", 1)
        out[rel] = h
    return out


def write_manifest(path: Path, hashes: dict) -> None:
    lines = [f"{h}\t{rel}" for rel, h in sorted(hashes.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_secret(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def extract_entities(file_text: str, source_path: str) -> dict:
    api_key = read_secret(LITELLM_API_KEY_FILE)
    resp = httpx.post(
        f"{LITELLM_BASE_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": LITELLM_MODEL,
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"Source path: {source_path}\n\n{file_text[:12000]}"},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


_PROP_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def build_cypher(extraction: dict, source_path: str) -> str:
    stmts = []
    valid_names = set()
    for e in extraction.get("entities", []) or []:
        cls = e.get("class")
        name = e.get("name")
        if cls not in KNOWN_CLASSES or not name:
            log(f"skipping invalid entity (bad class/name): {e}")
            continue
        name_esc = esc(name)
        props = e.get("properties") or {}
        prop_lines = ", ".join(
            f"n.{k} = '{esc(str(v))}'" for k, v in props.items()
            if _PROP_KEY_RE.match(k)
        )
        set_clause = f" SET {prop_lines}" if prop_lines else ""
        stmts.append(
            f"MERGE (n:Entity:{cls} {{name: '{name_esc}'}}){set_clause} "
            f"SET n.source_path = '{esc(source_path)}';"
        )
        valid_names.add(name)
    for r in extraction.get("relationships", []) or []:
        from_name, rel_type, to_name = r.get("from_name"), r.get("type"), r.get("to_name")
        if not from_name or not rel_type or not to_name:
            log(f"skipping invalid relationship: {r}")
            continue
        stmts.append(
            f"MATCH (a {{name: '{esc(from_name)}'}}) "
            f"MATCH (b {{name: '{esc(to_name)}'}}) "
            f"MERGE (a)-[:{re.sub(r'[^A-Za-z0-9_]', '_', rel_type.upper())}]->(b);"
        )
    return "\n".join(stmts)


def apply_cypher(driver, cypher_text: str) -> None:
    with driver.session() as session:
        for stmt in cypher_text.split(";\n"):
            stmt = stmt.strip().rstrip(";")
            if stmt:
                session.run(stmt)


def emit_lineage_event(run_id: str, inputs: list, outputs: list) -> None:
    event = {
        "eventType": "COMPLETE",
        "eventTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "run": {"runId": run_id},
        "job": {"namespace": "cluster-ontology-neo4j", "name": "vault-sync-autoextract"},
        "inputs": [{"namespace": "fardustdev-compose-vault", "name": p} for p in inputs],
        "outputs": [{"namespace": "cluster-ontology-neo4j", "name": o} for o in outputs],
        "producer": "https://github.com/anthropics/claude-code",
        "schemaURL": "https://openlineage.io/spec/1-0-5/OpenLineage.json#/$defs/RunEvent",
    }
    try:
        r = httpx.post(f"{MARQUEZ_URL}/api/v1/lineage", json=event, timeout=15.0)
        log(f"lineage event posted: HTTP {r.status_code}")
    except Exception as exc:
        log(f"lineage event failed (non-fatal): {exc}")


def sync_once(driver) -> None:
    current = compute_hashes(VAULT_ROOT)
    previous = load_manifest(MANIFEST_PATH)

    new_files = sorted(set(current) - set(previous))
    changed_files = sorted(
        rel for rel in (set(current) & set(previous)) if current[rel] != previous[rel]
    )
    deleted_files = sorted(set(previous) - set(current))

    log(f"sync check: {len(new_files)} new, {len(changed_files)} changed, {len(deleted_files)} deleted")

    to_process = new_files + changed_files
    if not to_process:
        return

    run_id = str(uuid.uuid4())
    outputs = []
    for rel in to_process:
        full_path = VAULT_ROOT / rel
        text = full_path.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 20:
            continue
        try:
            extraction = extract_entities(text, rel)
        except Exception as exc:
            log(f"extraction failed for {rel}: {exc}")
            continue
        cypher = build_cypher(extraction, rel)
        if not cypher.strip():
            continue
        if DRY_RUN:
            log(f"[DRY_RUN] would apply for {rel}:\n{cypher}")
        else:
            apply_cypher(driver, cypher)
            log(f"applied {len(extraction.get('entities', []))} entities / "
                f"{len(extraction.get('relationships', []))} rels for {rel}")
        outputs.append(f"entities-from:{rel}")

    if outputs and not DRY_RUN:
        emit_lineage_event(run_id, to_process, outputs)

    if not DRY_RUN:
        write_manifest(MANIFEST_PATH, current)
    else:
        log("[DRY_RUN] manifest NOT updated")


def main():
    log(f"vault-sync starting, DRY_RUN={DRY_RUN}, interval={SYNC_INTERVAL_SECONDS}s, root={VAULT_ROOT}")
    password = read_secret(NEO4J_PASSWORD_FILE).split("/", 1)[1]
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, password))
    driver.verify_connectivity()
    log("neo4j connectivity verified")

    while True:
        try:
            sync_once(driver)
        except Exception as exc:
            log(f"sync_once failed (will retry next interval): {exc}")
        time.sleep(SYNC_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
