"""
Knowledge Graph — Phase 6 Ontology & Knowledge Graph Storage
A-MEM Agentic Memory Architecture V1.0

Implements a Neo4j-inspired knowledge graph for A-MEM with:
- Entity nodes (CVE, Actor, Tool, Campaign, Asset, Note)
- Relationship edges with semantic types
- JSONL persistence with atomic writes
- Temporal indexing for time-based queries (Task 2)

Temporal Graph Extension (2026-04-06):
- Added temporal edge types: TEMPORAL_BEFORE, TEMPORAL_AFTER, SUPERSEDES
- Added temporal index for time-range queries
- Supports "what changed since X" queries
"""

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class KnowledgeGraph:
    """
    Knowledge graph storage with temporal indexing.
    Uses JSONL for append-only persistence.
    """

    def __init__(self, data_dir: Optional[str] = None):
        from zettelforge.memory_store import get_default_data_dir

        base_dir = Path(data_dir) if data_dir else get_default_data_dir()
        self.nodes_file = base_dir / "kg_nodes.jsonl"
        self.edges_file = base_dir / "kg_edges.jsonl"

        # In-memory caches
        self._nodes: Dict[str, Dict] = {}  # node_id -> node data
        self._node_index: Dict[str, Dict[str, str]] = {}  # entity_type -> entity_value -> node_id
        self._edges: Dict[str, Dict] = {}  # edge_id -> edge data
        self._edges_from: Dict[str, List[Dict]] = {}  # node_id -> outgoing edges
        self._edges_to: Dict[str, List[Dict]] = {}  # node_id -> incoming edges

        # ===== Temporal Index (Task 2) =====
        # Temporal edges indexed by timestamp
        self._temporal_index: Dict[str, List[Dict]] = {}  # timestamp -> temporal edges
        self._entity_timeline: Dict[str, List[Dict]] = {}  # entity_value -> timeline of states

        self._lock = threading.RLock()
        self._load_all()

    def _load_all(self):
        """Load nodes and edges from JSONL files."""
        if self.nodes_file.exists():
            with open(self.nodes_file, "r") as f:
                for line in f:
                    if line.strip():
                        try:
                            node = json.loads(line)
                            self._cache_node(node)
                        except json.JSONDecodeError:
                            continue

        if self.edges_file.exists():
            with open(self.edges_file, "r") as f:
                for line in f:
                    if line.strip():
                        try:
                            edge = json.loads(line)
                            self._cache_edge(edge)
                            # Index temporal edges
                            if (
                                edge.get("relationship", "").startswith("TEMPORAL_")
                                or edge.get("relationship") == "SUPERSEDES"
                            ):
                                self._index_temporal_edge(edge)
                        except json.JSONDecodeError:
                            continue

    def _cache_node(self, node: Dict):
        self._nodes[node["node_id"]] = node
        etype = node["entity_type"]
        evalue = node["entity_value"]
        if etype not in self._node_index:
            self._node_index[etype] = {}
        self._node_index[etype][evalue] = node["node_id"]

    def _cache_edge(self, edge: Dict):
        self._edges[edge["edge_id"]] = edge

        from_id = edge["from_node_id"]
        to_id = edge["to_node_id"]

        if from_id not in self._edges_from:
            self._edges_from[from_id] = []
        existing = next(
            (e for e in self._edges_from[from_id] if e["edge_id"] == edge["edge_id"]), None
        )
        if existing:
            existing.update(edge)
        else:
            self._edges_from[from_id].append(edge)

        if to_id not in self._edges_to:
            self._edges_to[to_id] = []
        existing_to = next(
            (e for e in self._edges_to[to_id] if e["edge_id"] == edge["edge_id"]), None
        )
        if existing_to:
            existing_to.update(edge)
        else:
            self._edges_to[to_id].append(edge)

    # ===== Temporal Indexing (Task 2) =====

    def _parse_timestamp(self, ts_string: str) -> Optional[datetime]:
        """Parse various timestamp formats."""
        if not ts_string:
            return None

        # ISO format
        try:
            return datetime.fromisoformat(ts_string.replace("Z", "+00:00"))
        except Exception:
            pass

        # Common formats
        formats = ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d %b %Y", "%B %d, %Y"]
        for fmt in formats:
            try:
                return datetime.strptime(ts_string, fmt)
            except Exception:
                continue
        return None

    def _index_temporal_edge(self, edge: Dict):
        """Index a temporal edge in the temporal index."""
        ts = edge.get("properties", {}).get("timestamp") or edge.get("created_at", "")
        if ts:
            if ts not in self._temporal_index:
                self._temporal_index[ts] = []
            self._temporal_index[ts].append(edge)

        # Also index in entity timeline
        from_node = self._nodes.get(edge.get("from_node_id"), {})
        to_node = self._nodes.get(edge.get("to_node_id"), {})

        entity_key = f"{from_node.get('entity_type')}:{from_node.get('entity_value')}"
        if entity_key not in self._entity_timeline:
            self._entity_timeline[entity_key] = []

        self._entity_timeline[entity_key].append(
            {
                "edge": edge,
                "timestamp": ts,
                "to_entity": f"{to_node.get('entity_type')}:{to_node.get('entity_value')}",
            }
        )

    def add_temporal_edge(
        self,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        relationship: str,  # TEMPORAL_BEFORE, TEMPORAL_AFTER, SUPERSEDES
        timestamp: str,
        properties: Optional[Dict] = None,
    ) -> str:
        """Add a temporal edge with timestamp."""
        props = properties or {}
        props["timestamp"] = timestamp

        edge_id = self.add_edge(from_type, from_value, to_type, to_value, relationship, props)

        # Index in temporal structures
        edge = self._edges.get(edge_id)
        if edge:
            self._index_temporal_edge(edge)

        return edge_id

    def get_entity_timeline(self, entity_type: str, entity_value: str) -> List[Dict]:
        """Get timeline of states for an entity.  [Enterprise]"""
        from zettelforge.edition import EditionError, is_enterprise

        if not is_enterprise():
            raise EditionError(
                "'get_entity_timeline' (temporal knowledge graph queries) requires "
                "ThreatRecall Enterprise. https://threatengram.com/enterprise"
            )
        entity_key = f"{entity_type}:{entity_value}"
        timeline = self._entity_timeline.get(entity_key, [])

        # Sort by timestamp
        timeline.sort(key=lambda x: x["timestamp"] or "")
        return timeline

    def get_changes_since(self, timestamp: str) -> List[Dict]:
        """Get all entity changes since a given timestamp.  [Enterprise]"""
        from zettelforge.edition import EditionError, is_enterprise

        if not is_enterprise():
            raise EditionError(
                "'get_changes_since' (temporal knowledge graph queries) requires "
                "ThreatRecall Enterprise. https://threatengram.com/enterprise"
            )
        changes = []

        for ts, edges in self._temporal_index.items():
            if ts >= timestamp:
                for edge in edges:
                    from_node = self._nodes.get(edge.get("from_node_id"), {})
                    to_node = self._nodes.get(edge.get("to_node_id"), {})
                    changes.append(
                        {
                            "timestamp": ts,
                            "from": f"{from_node.get('entity_type')}:{from_node.get('entity_value')}",
                            "relationship": edge.get("relationship"),
                            "to": f"{to_node.get('entity_type')}:{to_node.get('entity_value')}",
                        }
                    )

        changes.sort(key=lambda x: x["timestamp"])
        return changes

    # ===== Core Graph Operations =====

    def add_node(
        self, entity_type: str, entity_value: str, properties: Optional[Dict] = None
    ) -> str:
        """Add or update a node. Returns node_id."""
        with self._lock:
            # Check if exists
            if entity_type in self._node_index and entity_value in self._node_index[entity_type]:
                node_id = self._node_index[entity_type][entity_value]
                node = self._nodes[node_id]
                if properties:
                    node["properties"].update(properties)
                    node["updated_at"] = datetime.now().isoformat()
                    self._append_jsonl(self.nodes_file, node)
                return node_id

            # Create new
            node_id = f"node_{uuid.uuid4().hex[:12]}"
            node = {
                "node_id": node_id,
                "entity_type": entity_type,
                "entity_value": entity_value,
                "properties": properties or {},
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            self._cache_node(node)
            self._append_jsonl(self.nodes_file, node)
            return node_id

    def add_edge(
        self,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        relationship: str,
        properties: Optional[Dict] = None,
    ) -> str:
        """Add or update a relationship edge between two entities. Auto-creates nodes."""
        with self._lock:
            from_id = self.add_node(from_type, from_value)
            to_id = self.add_node(to_type, to_value)

            # Check if edge exists
            existing = None
            for edge in self._edges_from.get(from_id, []):
                if edge["to_node_id"] == to_id and edge["relationship"] == relationship:
                    existing = edge
                    break

            if existing:
                if properties:
                    existing["properties"].update(properties)
                    existing["updated_at"] = datetime.now().isoformat()
                    self._append_jsonl(self.edges_file, existing)
                return existing["edge_id"]

            # Create new edge
            edge_id = f"edge_{uuid.uuid4().hex[:12]}"
            edge = {
                "edge_id": edge_id,
                "from_node_id": from_id,
                "to_node_id": to_id,
                "relationship": relationship,
                "properties": properties or {},
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            self._cache_edge(edge)
            self._append_jsonl(self.edges_file, edge)

            # Index temporal edges
            if relationship.startswith("TEMPORAL_") or relationship == "SUPERSEDES":
                self._index_temporal_edge(edge)

            return edge_id

    def _append_jsonl(self, path: Path, data: Dict):
        """Append to JSONL file atomically-ish."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(data) + "\n")

    def get_node(self, entity_type: str, entity_value: str) -> Optional[Dict]:
        """Get node by type and value."""
        node_id = self._node_index.get(entity_type, {}).get(entity_value)
        if node_id:
            return self._nodes.get(node_id)
        return None

    def get_node_by_id(self, node_id: str) -> Optional[Dict]:
        """Get node by its internal node_id."""
        return self._nodes.get(node_id)

    def get_outgoing_edges(self, node_id: str) -> List[Dict]:
        """Return all outgoing edges for a node_id.

        Each edge dict contains at minimum: edge_id, from_node_id, to_node_id,
        relationship, properties, created_at, updated_at.
        """
        return list(self._edges_from.get(node_id, []))

    def get_neighbors(
        self, entity_type: str, entity_value: str, relationship: Optional[str] = None
    ) -> List[Dict]:
        """Get all adjacent nodes (outgoing edges) for a given node."""
        node_id = self._node_index.get(entity_type, {}).get(entity_value)
        if not node_id:
            return []

        neighbors = []
        for edge in self._edges_from.get(node_id, []):
            if relationship and edge["relationship"] != relationship:
                continue
            to_node = self._nodes.get(edge["to_node_id"])
            if to_node:
                neighbors.append(
                    {
                        "node": to_node,
                        "relationship": edge["relationship"],
                        "edge_properties": edge.get("properties", {}),
                    }
                )
        return neighbors

    def traverse(self, start_type: str, start_value: str, max_depth: int = 2) -> List[Dict]:
        """Traverse the graph up to max_depth."""
        start_node_id = self._node_index.get(start_type, {}).get(start_value)
        if not start_node_id:
            return []

        visited = set()
        results = []

        def _dfs(current_id, depth, path):
            if depth > max_depth or current_id in visited:
                return
            visited.add(current_id)

            for edge in self._edges_from.get(current_id, []):
                to_id = edge["to_node_id"]
                rel = edge["relationship"]
                to_node = self._nodes.get(to_id)
                if not to_node:
                    continue

                step = {
                    "from_type": self._nodes[current_id]["entity_type"],
                    "from_value": self._nodes[current_id]["entity_value"],
                    "relationship": rel,
                    "to_type": to_node["entity_type"],
                    "to_value": to_node["entity_value"],
                }
                new_path = path + [step]
                results.append(new_path)
                _dfs(to_id, depth + 1, new_path)

        _dfs(start_node_id, 1, [])
        return results

    def get_latest_state(self, entity_type: str, entity_value: str) -> Optional[Dict]:
        """Get the latest known state of an entity.  [Enterprise]"""
        timeline = self.get_entity_timeline(entity_type, entity_value)  # gate enforced there
        if timeline:
            return timeline[-1]
        return None


# Global singleton
_kg_instance: Optional[KnowledgeGraph] = None
_kg_lock = threading.Lock()


def get_knowledge_graph() -> KnowledgeGraph:
    """Get global knowledge graph instance.

    Enterprise: Tries TypeDB first, falls back to JSONL.
    Community: Always uses JSONL.
    """
    global _kg_instance
    if _kg_instance is None:
        with _kg_lock:
            if _kg_instance is None:
                from zettelforge.edition import is_enterprise

                backend = os.environ.get("ZETTELFORGE_BACKEND", "typedb")
                if backend == "typedb" and is_enterprise():
                    try:
                        from zettelforge_enterprise.typedb_client import TypeDBKnowledgeGraph

                        _kg_instance = TypeDBKnowledgeGraph()
                    except Exception as e:
                        from zettelforge.log import get_logger as _get_logger

                        _get_logger("zettelforge.kg").warning(
                            "typedb_unavailable_fallback_jsonl", error=str(e)
                        )
                        _kg_instance = KnowledgeGraph()
                else:
                    if backend == "typedb" and not is_enterprise():
                        from zettelforge.log import get_logger as _get_logger

                        _get_logger("zettelforge.edition").info(
                            "community_edition_jsonl_graph",
                            detail="TypeDB STIX ontology requires Enterprise edition",
                        )
                    _kg_instance = KnowledgeGraph()
    return _kg_instance
