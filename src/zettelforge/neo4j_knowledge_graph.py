"""Neo4j graph backend for the ZettelForge knowledge graph.

This module gives operators a real graph database for the one operation the
default backend has no native operator for: undirected ``shortestPath`` /
relationship discovery (~20x faster on real CTI data). It is a scoped, opt-in
path-query seam, NOT a wholesale storage backend: enable it with
``ZETTELFORGE_NEO4J_PATHFINDING=true`` and call
:func:`zettelforge.knowledge_graph.find_shortest_path`. SQLite/JSONL stays the
storage, recall, and traversal path (Neo4j regresses bounded traversal ~6x, so
it is deliberately not wired as ``ZETTELFORGE_BACKEND=neo4j``). The full
``KnowledgeGraph`` interface below is still implemented method-for-method so the
backend can be loaded with parity-checked data and benchmarked. Non-opt-in
deployments are unaffected and gain zero new mandatory dependencies.

Canonical read/write path (research R1):
    The production recall path traverses the per-store graph via
    ``StorageBackend`` (``SQLiteBackend.get_kg_neighbors`` / ``traverse_kg``
    over the SQLite ``kg_edges`` table), NOT the process-global JSONL
    ``KnowledgeGraph`` returned by ``get_knowledge_graph()``. The JSONL
    ``KnowledgeGraph`` is the public graph interface this class implements
    for drop-in parity, and is what ``get_knowledge_graph()`` hands out.
    ``Neo4jKnowledgeGraph`` therefore implements that ``KnowledgeGraph``
    contract method-for-method so it is a drop-in replacement; the benchmark
    separately compares it against the real SQLite traversal path, which is
    the baseline operators actually care about.

Mapping (research R3):
    Node identity is ``(entity_type, entity_value)`` enforced by ``MERGE``
    on a ``:Entity`` label. Edges are a single ``:REL`` relationship type
    with the semantic label stored as ``relationship`` and deduplicated on
    ``(from, to, relationship)`` via ``MERGE``. ``edge_type`` defaults to
    ``heuristic`` and is promoted (only) from ``heuristic`` to a more
    specific type on update, matching the default backend. Relationships
    starting ``TEMPORAL_`` or equal to ``SUPERSEDES`` are temporal.

Failure handling (research R5 / FR-008):
    Connection or auth failure raises :class:`Neo4jUnavailableError` (logged),
    never reporting a dropped write as successful. Fallback to the default
    backend happens only when explicitly configured
    (``ZETTELFORGE_NEO4J_FALLBACK=true``), handled in
    ``get_knowledge_graph()`` — never silently inside this class.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar

from zettelforge.config import get_config
from zettelforge.log import get_logger

if TYPE_CHECKING:
    from neo4j import Driver, ManagedTransaction

_logger = get_logger("zettelforge.neo4j_knowledge_graph")

# Return type of a transaction function, threaded through the executor helpers
# so the concrete return type flows out of execute_read/execute_write.
_T = TypeVar("_T")


class Neo4jUnavailableError(RuntimeError):
    """Neo4j is unreachable, misconfigured, or the driver extra is missing.

    Raised loud (FR-008) so an outage never silently drops a write or
    returns an empty graph as if it were real.
    """


class Neo4jKnowledgeGraph:
    """Knowledge graph backed by Neo4j, implementing the ``KnowledgeGraph``
    public interface with identical signatures and return shapes.

    Holds one lazily-created module-style ``Driver`` (thread-safe, pooled)
    and opens a short-lived managed-transaction session per operation.
    """

    def __init__(self, *, _skip_init_schema: bool = False) -> None:
        cfg = get_config().neo4j
        self._uri = cfg.uri
        self._user = cfg.user
        self._password = cfg.password
        self._database = cfg.database
        self._max_depth = cfg.max_depth
        self._result_limit = cfg.result_limit
        self._driver: Driver | None = None
        self._driver_lock = threading.Lock()
        # Tri-state APOC availability: None = unprobed, True/False after probe.
        self._apoc_available: bool | None = None
        # Surfaced so callers can see when a high-degree hub traversal hit
        # the configured result limit instead of being silently truncated.
        self.last_limit_hit: bool = False
        if not _skip_init_schema:
            self._init_schema()

    # ── Driver / session management ──────────────────────────────────────

    def _get_driver(self) -> Driver:
        """Return the shared driver, creating and verifying it on first use.

        Raises :class:`Neo4jUnavailableError` if the ``neo4j`` extra is not
        installed or the database cannot be reached.
        """
        if self._driver is not None:
            return self._driver
        with self._driver_lock:
            if self._driver is not None:
                return self._driver
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:
                _logger.error("neo4j_driver_missing", error=str(exc))
                raise Neo4jUnavailableError(
                    "The 'neo4j' driver is not installed. "
                    'Install the optional extra: pip install "zettelforge[neo4j]"'
                ) from exc
            driver = None
            try:
                # warn_notification_severity OFF silences benign
                # "UnknownPropertyKey" notifications emitted before any node
                # has carried a given property (first writes to an empty DB).
                driver = GraphDatabase.driver(
                    self._uri,
                    auth=(self._user, self._password),
                    warn_notification_severity="OFF",
                )
                driver.verify_connectivity()
            except Exception as exc:
                # Close the half-open driver on a failed connect so we fail
                # clean (Law 4): don't leak a driver/session every outage.
                if driver is not None:
                    driver.close()
                _logger.error(
                    "neo4j_unavailable", uri=self._uri, database=self._database, error=str(exc)
                )
                raise Neo4jUnavailableError(
                    f"Cannot connect to Neo4j at {self._uri} (database={self._database!r}): {exc}"
                ) from exc
            self._driver = driver
            _logger.info("neo4j_driver_connected", uri=self._uri, database=self._database)
            return driver

    def _execute_write(self, fn: Callable[..., _T], **kwargs: Any) -> _T:
        driver = self._get_driver()
        try:
            with driver.session(database=self._database) as session:
                return session.execute_write(fn, **kwargs)
        except Neo4jUnavailableError:
            raise
        except Exception as exc:
            _logger.error("neo4j_write_failed", error=str(exc))
            raise Neo4jUnavailableError(f"Neo4j write failed: {exc}") from exc

    def _execute_read(self, fn: Callable[..., _T], **kwargs: Any) -> _T:
        driver = self._get_driver()
        try:
            with driver.session(database=self._database) as session:
                return session.execute_read(fn, **kwargs)
        except Neo4jUnavailableError:
            raise
        except Exception as exc:
            _logger.error("neo4j_read_failed", error=str(exc))
            raise Neo4jUnavailableError(f"Neo4j read failed: {exc}") from exc

    def close(self) -> None:
        """Close the shared driver, if one was created."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    # ── Schema init ──────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        """Create the node-identity constraint and traversal indexes.

        Community edition supports a composite uniqueness constraint on
        ``(:Entity entity_type, entity_value)`` (NODE KEY is enterprise-only),
        which both enforces identity and provides the lookup index. Edge
        property indexes accelerate relationship- and edge_type-filtered
        reads.
        """
        statements = [
            "CREATE CONSTRAINT entity_identity IF NOT EXISTS "
            "FOR (n:Entity) REQUIRE (n.entity_type, n.entity_value) IS UNIQUE",
            "CREATE INDEX rel_relationship IF NOT EXISTS FOR ()-[r:REL]-() ON (r.relationship)",
            "CREATE INDEX rel_edge_type IF NOT EXISTS FOR ()-[r:REL]-() ON (r.edge_type)",
            "CREATE INDEX entity_node_id IF NOT EXISTS FOR (n:Entity) ON (n.node_id)",
        ]
        driver = self._get_driver()
        with driver.session(database=self._database) as session:
            for stmt in statements:
                session.run(stmt)
            # Constraints/indexes populate asynchronously. Block until they are
            # online so the very next MERGE is backed by the uniqueness
            # constraint; otherwise concurrent/batched MERGEs can create
            # duplicate nodes (no online index to dedup against).
            session.run("CALL db.awaitIndexes(300)")

    # ── Encoding helpers ─────────────────────────────────────────────────

    @staticmethod
    def _encode_props(properties: dict[str, Any] | None) -> str:
        """JSON-encode an arbitrary properties map for storage on a node/edge."""
        return json.dumps(properties or {})

    @staticmethod
    def _decode_props(raw: Any) -> dict[str, Any]:
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @classmethod
    def _node_out(cls, n: Any) -> dict[str, Any]:
        """Map a Neo4j node record to the default backend's node dict shape."""
        return {
            "node_id": n["node_id"],
            "entity_type": n["entity_type"],
            "entity_value": n["entity_value"],
            "properties": cls._decode_props(n.get("properties")),
            "created_at": n.get("created_at"),
            "updated_at": n.get("updated_at"),
        }

    @classmethod
    def _edge_out(cls, r: Any) -> dict[str, Any]:
        """Map a Neo4j relationship record to the default backend's edge dict shape."""
        return {
            "edge_id": r["edge_id"],
            "from_node_id": r["from_node_id"],
            "to_node_id": r["to_node_id"],
            "relationship": r["relationship"],
            "edge_type": r.get("edge_type", "heuristic"),
            "note_id": r.get("note_id"),
            "properties": cls._decode_props(r.get("properties")),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        }

    # ── Core node operations ─────────────────────────────────────────────

    def add_node(
        self, entity_type: str, entity_value: str, properties: dict[str, Any] | None = None
    ) -> str:
        """Add or update a node. Idempotent on ``(entity_type, entity_value)``.

        Returns the stable ``node_id``. On an existing node, merges the
        supplied properties (matching the default backend's update semantics).
        """
        return self._execute_write(
            self._tx_add_node,
            entity_type=entity_type,
            entity_value=entity_value,
            properties=properties,
        )

    @classmethod
    def _tx_add_node(
        cls,
        tx: ManagedTransaction,
        entity_type: str,
        entity_value: str,
        properties: dict[str, Any] | None,
    ) -> str:
        now = datetime.now().isoformat()
        # Read existing properties so we can merge rather than overwrite.
        rec = tx.run(
            "MATCH (n:Entity {entity_type:$t, entity_value:$v}) "
            "RETURN n.node_id AS node_id, n.properties AS properties",
            t=entity_type,
            v=entity_value,
        ).single()
        if rec is not None:
            if properties:
                merged = cls._decode_props(rec["properties"])
                merged.update(properties)
                tx.run(
                    "MATCH (n:Entity {entity_type:$t, entity_value:$v}) "
                    "SET n.properties = $props, n.updated_at = $now",
                    t=entity_type,
                    v=entity_value,
                    props=cls._encode_props(merged),
                    now=now,
                )
            return str(rec["node_id"])

        node_id = f"node_{uuid.uuid4().hex[:12]}"
        tx.run(
            "MERGE (n:Entity {entity_type:$t, entity_value:$v}) "
            "ON CREATE SET n.node_id = $nid, n.properties = $props, "
            "n.created_at = $now, n.updated_at = $now",
            t=entity_type,
            v=entity_value,
            nid=node_id,
            props=cls._encode_props(properties),
            now=now,
        )
        return node_id

    def get_node(self, entity_type: str, entity_value: str) -> dict[str, Any] | None:
        """Get a node by type and value, or ``None``."""
        return self._execute_read(
            self._tx_get_node, entity_type=entity_type, entity_value=entity_value
        )

    @classmethod
    def _tx_get_node(
        cls, tx: ManagedTransaction, entity_type: str, entity_value: str
    ) -> dict[str, Any] | None:
        rec = tx.run(
            "MATCH (n:Entity {entity_type:$t, entity_value:$v}) RETURN n",
            t=entity_type,
            v=entity_value,
        ).single()
        return cls._node_out(rec["n"]) if rec else None

    def get_node_by_id(self, node_id: str) -> dict[str, Any] | None:
        """Get a node by its internal ``node_id``, or ``None``."""
        return self._execute_read(self._tx_get_node_by_id, node_id=node_id)

    @classmethod
    def _tx_get_node_by_id(cls, tx: ManagedTransaction, node_id: str) -> dict[str, Any] | None:
        rec = tx.run("MATCH (n:Entity {node_id:$nid}) RETURN n", nid=node_id).single()
        return cls._node_out(rec["n"]) if rec else None

    # ── Core edge operations ─────────────────────────────────────────────

    def add_edge(
        self,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        relationship: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """Add or update a directional edge. Auto-creates nodes.

        Deduplicated on ``(from, to, relationship)`` via ``MERGE``. ``edge_type``
        is taken from ``properties`` (default ``heuristic``) and promoted from
        ``heuristic`` to a more specific type on update. The remaining
        properties are merged. Returns the stable ``edge_id``.
        """
        return self._execute_write(
            self._tx_add_edge,
            from_type=from_type,
            from_value=from_value,
            to_type=to_type,
            to_value=to_value,
            relationship=relationship,
            properties=properties,
        )

    @classmethod
    def _tx_add_edge(
        cls,
        tx: ManagedTransaction,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        relationship: str,
        properties: dict[str, Any] | None,
    ) -> str:
        now = datetime.now().isoformat()
        # Ensure both endpoints exist (idempotent), capturing their ids.
        from_id = cls._tx_add_node(tx, from_type, from_value, None)
        to_id = cls._tx_add_node(tx, to_type, to_value, None)

        props = dict(properties or {})
        incoming_edge_type = props.pop("edge_type", None)
        incoming_note_id = props.pop("note_id", None)
        incoming_confidence = props.pop("confidence", None)

        existing = tx.run(
            "MATCH (a:Entity {node_id:$fid})-[r:REL {relationship:$rel}]->(b:Entity {node_id:$tid}) "
            "RETURN r.edge_id AS edge_id, r.edge_type AS edge_type, r.properties AS properties, "
            "r.note_id AS note_id, r.confidence AS confidence",
            fid=from_id,
            tid=to_id,
            rel=relationship,
        ).single()

        if existing is not None:
            edge_type = existing["edge_type"]
            # Promote heuristic -> more specific, matching the default backend.
            if incoming_edge_type and edge_type == "heuristic":
                edge_type = incoming_edge_type
            merged = cls._decode_props(existing["properties"])
            if props:
                merged.update(props)
            tx.run(
                "MATCH (a:Entity {node_id:$fid})-[r:REL {relationship:$rel}]->(b:Entity {node_id:$tid}) "
                "SET r.edge_type = $etype, r.properties = $props, r.updated_at = $now, "
                "r.note_id = coalesce($note_id, r.note_id), "
                "r.confidence = coalesce($confidence, r.confidence)",
                fid=from_id,
                tid=to_id,
                rel=relationship,
                etype=edge_type,
                props=cls._encode_props(merged),
                now=now,
                note_id=incoming_note_id,
                confidence=incoming_confidence,
            )
            return str(existing["edge_id"])

        edge_id = f"edge_{uuid.uuid4().hex[:12]}"
        edge_type = incoming_edge_type or "heuristic"
        tx.run(
            "MATCH (a:Entity {node_id:$fid}), (b:Entity {node_id:$tid}) "
            "MERGE (a)-[r:REL {relationship:$rel}]->(b) "
            "ON CREATE SET r.edge_id = $eid, r.from_node_id = $fid, r.to_node_id = $tid, "
            "r.edge_type = $etype, r.note_id = $note_id, r.confidence = $confidence, "
            "r.properties = $props, r.created_at = $now, r.updated_at = $now",
            fid=from_id,
            tid=to_id,
            rel=relationship,
            eid=edge_id,
            etype=edge_type,
            note_id=incoming_note_id,
            confidence=incoming_confidence,
            props=cls._encode_props(props),
            now=now,
        )
        return edge_id

    def add_temporal_edge(
        self,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        relationship: str,
        timestamp: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """Add a temporal edge with ``timestamp`` baked into its properties.

        Temporal relationships (``TEMPORAL_*`` / ``SUPERSEDES``) are queryable
        via :meth:`get_entity_timeline` and :meth:`get_changes_since` through
        the ``timestamp`` / ``created_at`` ordering, mirroring the default
        backend. Native graph storage needs no separate temporal index.
        """
        props = dict(properties or {})
        props["timestamp"] = timestamp
        return self.add_edge(from_type, from_value, to_type, to_value, relationship, props)

    def get_outgoing_edges(self, node_id: str) -> list[dict[str, Any]]:
        """Return all outgoing edges for a ``node_id`` in default-backend shape."""
        return self._execute_read(self._tx_get_outgoing_edges, node_id=node_id)

    @classmethod
    def _tx_get_outgoing_edges(cls, tx: ManagedTransaction, node_id: str) -> list[dict[str, Any]]:
        result = tx.run(
            "MATCH (a:Entity {node_id:$nid})-[r:REL]->(b:Entity) RETURN r",
            nid=node_id,
        )
        return [cls._edge_out(rec["r"]) for rec in result]

    def get_neighbors(
        self, entity_type: str, entity_value: str, relationship: str | None = None
    ) -> list[dict[str, Any]]:
        """Single-hop outgoing neighbors, optionally filtered by relationship.

        Each result is ``{"node": <node dict>, "relationship": str,
        "edge_properties": dict}``, matching the default backend.
        """
        return self._execute_read(
            self._tx_get_neighbors,
            entity_type=entity_type,
            entity_value=entity_value,
            relationship=relationship,
        )

    @classmethod
    def _tx_get_neighbors(
        cls,
        tx: ManagedTransaction,
        entity_type: str,
        entity_value: str,
        relationship: str | None,
    ) -> list[dict[str, Any]]:
        if relationship is not None:
            cypher = (
                "MATCH (a:Entity {entity_type:$t, entity_value:$v})-[r:REL {relationship:$rel}]->(b:Entity) "
                "RETURN b AS node, r AS rel"
            )
            result = tx.run(cypher, t=entity_type, v=entity_value, rel=relationship)
        else:
            cypher = (
                "MATCH (a:Entity {entity_type:$t, entity_value:$v})-[r:REL]->(b:Entity) "
                "RETURN b AS node, r AS rel"
            )
            result = tx.run(cypher, t=entity_type, v=entity_value)
        out: list[dict[str, Any]] = []
        for rec in result:
            r = rec["rel"]
            out.append(
                {
                    "node": cls._node_out(rec["node"]),
                    "relationship": r["relationship"],
                    "edge_properties": cls._decode_props(r.get("properties")),
                }
            )
        return out

    # ── Multi-hop traversal and path finding ─────────────────────────────

    def traverse(
        self, start_type: str, start_value: str, max_depth: int = 2
    ) -> list[dict[str, Any]]:
        """Multi-hop traversal up to ``max_depth`` via variable-length Cypher.

        Returns a list of paths; each path is a list of step dicts
        ``{from_type, from_value, relationship, to_type, to_value}`` matching
        the default backend. ``max_depth`` is capped by the configured
        ``ZETTELFORGE_NEO4J_MAX_DEPTH``. Results are bounded by the configured
        result limit; when the limit is reached, :attr:`last_limit_hit` is set
        so the cap is observable rather than a silent truncation.
        """
        depth = min(max_depth, self._max_depth)
        limit = self._result_limit
        paths, limit_hit = self._execute_read(
            self._tx_traverse,
            start_type=start_type,
            start_value=start_value,
            depth=depth,
            limit=limit,
        )
        self.last_limit_hit = limit_hit
        if limit_hit:
            _logger.warning(
                "neo4j_traverse_result_limit_hit",
                start=f"{start_type}:{start_value}",
                depth=depth,
                limit=limit,
            )
        return paths

    @classmethod
    def _tx_traverse(
        cls,
        tx: ManagedTransaction,
        start_type: str,
        start_value: str,
        depth: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        # Variable-length expansion. Each matched path of length 1..depth is
        # emitted as an ordered list of step dicts. The depth bound cannot be
        # a Cypher parameter inside a variable-length pattern, so it is coerced
        # to a validated int and inlined.
        d = max(1, int(depth))
        cypher = (
            f"MATCH p = (a:Entity {{entity_type:$t, entity_value:$v}})-[:REL*1..{d}]->(b:Entity) "
            "RETURN [rel IN relationships(p) | {"
            "from_type: startNode(rel).entity_type, "
            "from_value: startNode(rel).entity_value, "
            "relationship: rel.relationship, "
            "to_type: endNode(rel).entity_type, "
            "to_value: endNode(rel).entity_value}] AS steps"
        )
        params: dict[str, Any] = {"t": start_type, "v": start_value}
        if limit and limit > 0:
            cypher += " LIMIT $limit"
            params["limit"] = limit + 1
        result = tx.run(cypher, **params)
        paths = [rec["steps"] for rec in result]
        limit_hit = bool(limit and limit > 0 and len(paths) > limit)
        if limit_hit:
            paths = paths[:limit]
        return paths, limit_hit

    def _has_apoc(self) -> bool:
        """Return whether APOC procedures are callable, probing once and caching."""
        if self._apoc_available is not None:
            return self._apoc_available
        driver = self._get_driver()
        try:
            with driver.session(database=self._database) as session:
                session.run("RETURN apoc.version() AS v").single()
            self._apoc_available = True
        except Exception:
            self._apoc_available = False
        return self._apoc_available

    def reachable_nodes(
        self, start_type: str, start_value: str, max_depth: int = 2
    ) -> list[dict[str, Any]]:
        """Distinct nodes reachable within ``max_depth`` hops, with min hop count.

        This is the reachable-set traversal the production graph stage performs
        (``GraphRetriever`` collects distinct reachable nodes, not every path),
        done server-side in a single query instead of one round trip per visited
        node. Each result is ``{"node": <node dict>, "hops": int}``. Additive;
        the legacy per-path :meth:`traverse` is unchanged.

        Uses APOC's visited-set BFS (``apoc.path.subgraphNodes``) when available
        for a true O(V+E) expansion; falls back to plain variable-length Cypher
        otherwise.
        """
        depth = min(max_depth, self._max_depth)
        if self._has_apoc():
            return self._execute_read(
                self._tx_reachable_nodes_apoc,
                start_type=start_type,
                start_value=start_value,
                depth=depth,
                limit=self._result_limit,
            )
        return self._execute_read(
            self._tx_reachable_nodes,
            start_type=start_type,
            start_value=start_value,
            depth=depth,
            limit=self._result_limit,
        )

    def reachable_node_ids(
        self, start_type: str, start_value: str, max_depth: int = 2
    ) -> list[str]:
        """Just the distinct reachable ``node_id`` set within ``max_depth`` hops.

        The shape production recall actually needs (it scores note-ids, not full
        node objects), and the cheapest to serialize. Uses APOC's visited-set
        BFS when available. Returned server-side as scalars, so the Bolt payload
        is ids only — not full node maps.
        """
        depth = min(max_depth, self._max_depth)
        return self._execute_read(
            self._tx_reachable_node_ids,
            start_type=start_type,
            start_value=start_value,
            depth=depth,
            limit=self._result_limit,
            apoc=self._has_apoc(),
        )

    @classmethod
    def _tx_reachable_node_ids(
        cls,
        tx: ManagedTransaction,
        start_type: str,
        start_value: str,
        depth: int,
        limit: int,
        apoc: bool,
    ) -> list[str]:
        d = max(1, int(depth))
        if apoc:
            cypher = (
                "MATCH (a:Entity {entity_type:$t, entity_value:$v}) "
                "CALL apoc.path.subgraphNodes(a, {relationshipFilter:'REL>', maxLevel:$depth}) "
                "YIELD node WHERE node <> a RETURN node.node_id AS id"
            )
            params: dict[str, Any] = {"t": start_type, "v": start_value, "depth": d}
        else:
            cypher = (
                f"MATCH (a:Entity {{entity_type:$t, entity_value:$v}})-[:REL*1..{d}]->(b:Entity) "
                "RETURN DISTINCT b.node_id AS id"
            )
            params = {"t": start_type, "v": start_value}
        if limit and limit > 0:
            cypher += " LIMIT $limit"
            params["limit"] = limit
        return [rec["id"] for rec in tx.run(cypher, **params)]

    @classmethod
    def _tx_reachable_nodes_apoc(
        cls,
        tx: ManagedTransaction,
        start_type: str,
        start_value: str,
        depth: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        d = max(1, int(depth))
        cypher = (
            "MATCH (a:Entity {entity_type:$t, entity_value:$v}) "
            "CALL apoc.path.subgraphNodes(a, {relationshipFilter:'REL>', maxLevel:$depth}) "
            "YIELD node "
            "WHERE node <> a "
            "RETURN node"
        )
        params: dict[str, Any] = {"t": start_type, "v": start_value, "depth": d}
        if limit and limit > 0:
            cypher += " LIMIT $limit"
            params["limit"] = limit
        result = tx.run(cypher, **params)
        # subgraphNodes does not return hop distance; production scoring uses
        # 1/(1+hops) but the reachable SET is what recall needs. Hops omitted
        # here (the plain-Cypher path supplies them when APOC is absent).
        return [{"node": cls._node_out(rec["node"]), "hops": None} for rec in result]

    @classmethod
    def _tx_reachable_nodes(
        cls,
        tx: ManagedTransaction,
        start_type: str,
        start_value: str,
        depth: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        d = max(1, int(depth))
        # Match every bounded path, group by endpoint, keep the minimum path
        # length as the hop distance. No nested shortestPath (which errors when
        # start == end on a cycle); min(length(p)) over the matched paths is the
        # min hop count, and DISTINCT-by-endpoint via aggregation dedups nodes.
        cypher = (
            f"MATCH p = (a:Entity {{entity_type:$t, entity_value:$v}})-[:REL*1..{d}]->(b:Entity) "
            "WITH b, min(length(p)) AS hops "
            "RETURN b AS node, hops ORDER BY hops"
        )
        if limit and limit > 0:
            cypher += " LIMIT $limit"
            result = tx.run(cypher, t=start_type, v=start_value, limit=limit)
        else:
            result = tx.run(cypher, t=start_type, v=start_value)
        return [{"node": cls._node_out(rec["node"]), "hops": rec["hops"]} for rec in result]

    def shortest_path(
        self,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        max_depth: int | None = None,
    ) -> list[dict[str, Any]] | None:
        """Return the shortest path between two entities, or ``None`` if none.

        New, additive capability the default backend lacks. The path is an
        ordered list of step dicts (same shape as a single :meth:`traverse`
        path). ``max_depth`` defaults to the configured maximum. Direction is
        ignored for path finding (undirected ``shortestPath``) so an analyst
        can reach a target regardless of edge orientation.
        """
        depth = self._max_depth if max_depth is None else min(max_depth, self._max_depth)
        return self._execute_read(
            self._tx_shortest_path,
            from_type=from_type,
            from_value=from_value,
            to_type=to_type,
            to_value=to_value,
            depth=depth,
        )

    @classmethod
    def _tx_shortest_path(
        cls,
        tx: ManagedTransaction,
        from_type: str,
        from_value: str,
        to_type: str,
        to_value: str,
        depth: int,
    ) -> list[dict[str, Any]] | None:
        d = max(1, int(depth))
        cypher = (
            "MATCH (a:Entity {entity_type:$ft, entity_value:$fv}), "
            "(b:Entity {entity_type:$tt, entity_value:$tv}) "
            f"MATCH p = shortestPath((a)-[:REL*..{d}]-(b)) "
            "RETURN [rel IN relationships(p) | {"
            "from_type: startNode(rel).entity_type, "
            "from_value: startNode(rel).entity_value, "
            "relationship: rel.relationship, "
            "to_type: endNode(rel).entity_type, "
            "to_value: endNode(rel).entity_value}] AS steps"
        )
        rec = tx.run(cypher, ft=from_type, fv=from_value, tt=to_type, tv=to_value).single()
        if rec is None:
            return None
        return list(rec["steps"])

    # ── Causal queries ───────────────────────────────────────────────────

    def get_causal_edges(
        self,
        entity_type: str,
        entity_value: str,
        max_depth: int = 3,
        max_visited: int = 50,
    ) -> list[dict[str, Any]]:
        """Outgoing causal edges reachable from an entity (forward causal trace).

        Walks only ``edge_type='causal'`` edges, bounded by ``max_depth`` and
        ``max_visited``, returning edge dicts. Mirrors the default backend's
        forward causal BFS using a native variable-length causal path.
        """
        return self._execute_read(
            self._tx_causal,
            entity_type=entity_type,
            entity_value=entity_value,
            max_depth=max_depth,
            max_visited=max_visited,
            direction="out",
        )

    def get_incoming_causal(
        self,
        entity_type: str,
        entity_value: str,
        max_depth: int = 3,
        max_visited: int = 50,
    ) -> list[dict[str, Any]]:
        """Incoming causal edges (backward trace to root causes, 'why' queries)."""
        return self._execute_read(
            self._tx_causal,
            entity_type=entity_type,
            entity_value=entity_value,
            max_depth=max_depth,
            max_visited=max_visited,
            direction="in",
        )

    @classmethod
    def _tx_causal(
        cls,
        tx: ManagedTransaction,
        entity_type: str,
        entity_value: str,
        max_depth: int,
        max_visited: int,
        direction: str,
    ) -> list[dict[str, Any]]:
        d = max(1, int(max_depth))
        if direction == "out":
            pattern = f"(a:Entity {{entity_type:$t, entity_value:$v}})-[r:REL*1..{d}]->(b:Entity)"
        else:
            pattern = f"(a:Entity {{entity_type:$t, entity_value:$v}})<-[r:REL*1..{d}]-(b:Entity)"
        cypher = (
            f"MATCH p = {pattern} "
            "WHERE all(rel IN relationships(p) WHERE rel.edge_type = 'causal') "
            "UNWIND relationships(p) AS rel "
            "WITH DISTINCT rel "
            "RETURN rel "
            "LIMIT $cap"
        )
        # max_visited bounds nodes in the default backend; cap distinct edges
        # by a generous multiple of that node budget to stay bounded.
        result = tx.run(
            cypher,
            t=entity_type,
            v=entity_value,
            cap=max(max_visited, 1) * 50,
        )
        return [cls._edge_out(rec["rel"]) for rec in result]

    # ── Temporal queries ─────────────────────────────────────────────────

    def get_entity_timeline(self, entity_type: str, entity_value: str) -> list[dict[str, Any]]:
        """Ordered timeline of temporal edges out of an entity.

        Each item is ``{"edge": <edge dict>, "timestamp": str,
        "to_entity": "type:value"}`` ordered by timestamp, matching the
        default backend.
        """
        return self._execute_read(
            self._tx_timeline, entity_type=entity_type, entity_value=entity_value
        )

    @classmethod
    def _tx_timeline(
        cls, tx: ManagedTransaction, entity_type: str, entity_value: str
    ) -> list[dict[str, Any]]:
        result = tx.run(
            "MATCH (a:Entity {entity_type:$t, entity_value:$v})-[r:REL]->(b:Entity) "
            "WHERE r.relationship STARTS WITH 'TEMPORAL_' OR r.relationship = 'SUPERSEDES' "
            "RETURN r, b.entity_type AS to_type, b.entity_value AS to_value",
            t=entity_type,
            v=entity_value,
        )
        timeline: list[dict[str, Any]] = []
        for rec in result:
            edge = cls._edge_out(rec["r"])
            props = edge["properties"]
            ts = props.get("timestamp") or edge.get("created_at") or ""
            timeline.append(
                {
                    "edge": edge,
                    "timestamp": ts,
                    "to_entity": f"{rec['to_type']}:{rec['to_value']}",
                }
            )
        timeline.sort(key=lambda x: x["timestamp"] or "")
        return timeline

    def get_changes_since(self, timestamp: str) -> list[dict[str, Any]]:
        """All temporal edge changes at or after ``timestamp`` (ISO-8601)."""
        return self._execute_read(self._tx_changes_since, timestamp=timestamp)

    @classmethod
    def _tx_changes_since(cls, tx: ManagedTransaction, timestamp: str) -> list[dict[str, Any]]:
        result = tx.run(
            "MATCH (a:Entity)-[r:REL]->(b:Entity) "
            "WHERE (r.relationship STARTS WITH 'TEMPORAL_' OR r.relationship = 'SUPERSEDES') "
            "AND r.created_at >= $ts "
            "RETURN a.entity_type AS from_type, a.entity_value AS from_value, "
            "r.relationship AS relationship, r.created_at AS created_at, "
            "b.entity_type AS to_type, b.entity_value AS to_value "
            "ORDER BY r.created_at",
            ts=timestamp,
        )
        changes: list[dict[str, Any]] = []
        for rec in result:
            changes.append(
                {
                    "timestamp": rec["created_at"],
                    "from": f"{rec['from_type']}:{rec['from_value']}",
                    "relationship": rec["relationship"],
                    "to": f"{rec['to_type']}:{rec['to_value']}",
                }
            )
        return changes

    def get_latest_state(self, entity_type: str, entity_value: str) -> dict[str, Any] | None:
        """Latest temporal state of an entity, or ``None`` if no timeline."""
        timeline = self.get_entity_timeline(entity_type, entity_value)
        return timeline[-1] if timeline else None
