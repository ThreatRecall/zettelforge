---
title: "Set Up TypeDB for ZettelForge"
description: "Configure TypeDB as the knowledge graph backend using Docker Compose, load the STIX schema, seed aliases, and verify connectivity."
diataxis_type: "how-to"
audience: "Platform engineers deploying ZettelForge, CTI analysts setting up local environments"
tags: [typedb, docker, setup, configuration, knowledge-graph, schema]
last_updated: "2026-04-09"
version: "2.0.0"
---

# Set Up TypeDB for ZettelForge

Configure TypeDB as the knowledge graph backend. TypeDB stores STIX 2.1 entities, relationships, and alias-of mappings for structured CTI queries.

## Prerequisites

- Docker and Docker Compose installed
- ZettelForge installed (`pip install zettelforge`)

## Steps

### 1. Start TypeDB with Docker Compose

From the ZettelForge project root:

```bash
cd docker
docker compose up -d
```

Verify the container is running:

```bash
docker compose ps
```

Expected output:

```
NAME              IMAGE                COMMAND    SERVICE   STATUS
docker-typedb-1   typedb/typedb:latest ...        typedb    Up (healthy)
```

> [!NOTE]
> TypeDB exposes port `1729` (gRPC) and port `8100` (HTTP health). Data persists in the `typedb-data` Docker volume across restarts.

### 2. Verify connectivity

```python
from zettelforge.typedb_client import TypeDBKnowledgeGraph

try:
    kg = TypeDBKnowledgeGraph()
    print("TypeDB connection successful")
except Exception as e:
    print(f"Connection failed: {e}")
```

Or via the health endpoint:

```bash
curl -f http://localhost:8100/health
```

### 3. Load the STIX schema

The schema is loaded automatically on first connection via `TypeDBKnowledgeGraph`. To verify:

```python
from zettelforge.knowledge_graph import get_knowledge_graph

kg = get_knowledge_graph()
print(f"Backend: {type(kg).__name__}")
```

If TypeDB is reachable, this prints `TypeDBKnowledgeGraph`. If unreachable, it falls back to `KnowledgeGraph` (JSONL).

### 4. Seed alias relations

```bash
python -m zettelforge.schema.seed_aliases
```

```
Seeded 42 alias relations into TypeDB.
```

This inserts `alias-of` relations for known threat actors (APT28, APT29, Lazarus Group, Volt Typhoon, Sandworm, Kimsuky, Turla, MuddyWater) and tools (Cobalt Strike, Metasploit, Mimikatz).

### 5. Configure `config.yaml`

Copy the default configuration:

```bash
cp config.default.yaml config.yaml
```

Edit the TypeDB section:

```yaml
typedb:
  host: localhost
  port: 1729
  database: zettelforge
  username: admin
  password: password

backend: typedb
```

> [!TIP]
> `config.yaml` is in `.gitignore`. Safe for credentials. Environment variables override config file values.

### 6. Override with environment variables (optional)

```bash
export TYPEDB_HOST=localhost
export TYPEDB_PORT=1729
export TYPEDB_DATABASE=zettelforge
export ZETTELFORGE_BACKEND=typedb
```

Configuration resolution order (highest priority first):

1. Environment variables (`TYPEDB_HOST`, `TYPEDB_PORT`, etc.)
2. `config.yaml` in working directory
3. `config.yaml` in project root
4. `config.default.yaml` in project root
5. Hardcoded defaults in `config.py`

### 7. Verify the full stack

```python
from zettelforge.memory_manager import MemoryManager

mm = MemoryManager()

# Store a test note
note, status = mm.remember(
    content="APT28 deployed Cobalt Strike against NATO targets in 2026.",
    source_type="test",
    domain="cti"
)
print(f"Store: {status}")

# Query the graph
rels = mm.get_entity_relationships("actor", "apt28")
print(f"Graph relationships: {len(rels)}")

# Verify alias resolution through TypeDB
notes = mm.recall_actor("Fancy Bear")
print(f"Alias resolution: {len(notes)} notes found for 'Fancy Bear'")
```

## Troubleshooting

### TypeDB container fails to start

```bash
docker compose logs typedb
```

Common causes:
- Port 1729 already in use: `lsof -i :1729`
- Insufficient memory: TypeDB needs ~1GB RAM minimum

### Connection refused on port 1729

```bash
# Check container health
docker compose ps

# Restart if unhealthy
docker compose restart typedb

# Wait for health check to pass
docker compose exec typedb curl -f http://localhost:8000/health
```

### Fallback to JSONL backend

If TypeDB is unreachable, ZettelForge logs a warning and falls back to JSONL:

```
[WARNING] TypeDB unreachable, falling back to JSONL backend
```

To force JSONL mode (skip TypeDB entirely):

```yaml
backend: jsonl
```

Or:

```bash
export ZETTELFORGE_BACKEND=jsonl
```

> [!WARNING]
> JSONL fallback stores identical relationship data but does not support TypeQL queries or the `alias-of` relation type. Use the local JSON alias file (`~/.amem/entity_aliases.json`) for alias resolution in JSONL mode.

## LLM Quick Reference

**Task**: Set up TypeDB as the ZettelForge knowledge graph backend.

**Docker**: `docker compose up -d` from the `docker/` directory. Ports: 1729 (gRPC), 8100 (HTTP health). Volume: `typedb-data`.

**Schema**: Loaded automatically on first `TypeDBKnowledgeGraph()` instantiation. STIX 2.1 entity types: threat-actor, tool, malware, vulnerability, campaign, identity.

**Aliases**: `python -m zettelforge.schema.seed_aliases` inserts alias-of relations. Covers APT28, APT29, APT31, Lazarus, Sandworm, Volt Typhoon, Kimsuky, Turla, MuddyWater, Cobalt Strike, Metasploit, Mimikatz.

**Config keys**: `TYPEDB_HOST` (default "localhost"), `TYPEDB_PORT` (default 1729), `TYPEDB_DATABASE` (default "zettelforge"), `TYPEDB_USERNAME`, `TYPEDB_PASSWORD`, `ZETTELFORGE_BACKEND` ("typedb" or "jsonl").

**Fallback**: If `backend: typedb` and TypeDB is unreachable, falls back to JSONL with a warning. Set `backend: jsonl` to skip TypeDB entirely.

**Health check**: `curl -f http://localhost:8100/health` or `docker compose ps` for container status.
