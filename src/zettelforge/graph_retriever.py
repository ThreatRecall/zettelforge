"""
Graph Retriever - Knowledge graph traversal for note retrieval.

Traverses the KG starting from query entities, collects note IDs
reachable within max_depth hops, and scores them by proximity.
Score formula: 1 / (1 + hop_distance)
"""

from dataclasses import dataclass, field

from zettelforge.knowledge_graph import KnowledgeGraph


@dataclass
class ScoredResult:
    """A note found via graph traversal with its score and path."""

    note_id: str
    score: float
    hops: int
    path: list[str] = field(default_factory=list)


class GraphRetriever:
    """Retrieve notes by traversing the knowledge graph from query entities."""

    def __init__(self, knowledge_graph: KnowledgeGraph):
        self.kg = knowledge_graph

    def retrieve_note_ids(
        self,
        query_entities: dict[str, list[str]],
        max_depth: int = 2,
    ) -> list[ScoredResult]:
        if not query_entities:
            return []

        best: dict[str, ScoredResult] = {}

        for entity_type, values in query_entities.items():
            for entity_value in values:
                self._bfs_collect(entity_type, entity_value, max_depth, best)

        results = list(best.values())
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _bfs_collect(
        self,
        start_type: str,
        start_value: str,
        max_depth: int,
        best: dict[str, ScoredResult],
    ):
        start_node = self.kg.get_node(start_type, start_value)
        if not start_node:
            return

        start_node_id = start_node["node_id"]
        visited: set[str] = set()
        queue = [(start_node_id, 0, [f"{start_type}:{start_value}"])]

        while queue:
            current_id, depth, path = queue.pop(0)

            if current_id in visited:
                continue
            visited.add(current_id)

            node = self.kg.get_node_by_id(current_id)
            if not node:
                continue

            if node["entity_type"] == "note":
                note_id = node["entity_value"]
                score = 1.0 / (1.0 + depth)
                if note_id not in best or score > best[note_id].score:
                    best[note_id] = ScoredResult(
                        note_id=note_id,
                        score=score,
                        hops=depth,
                        path=path,
                    )

            if depth >= max_depth:
                continue

            for edge in self.kg.get_outgoing_edges(current_id):
                to_id = edge["to_node_id"]
                to_node = self.kg.get_node_by_id(to_id)
                if to_node and to_id not in visited:
                    step_label = f"{to_node['entity_type']}:{to_node['entity_value']}"
                    queue.append((to_id, depth + 1, [*path, step_label]))
