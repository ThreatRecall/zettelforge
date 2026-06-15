# Graph backend benchmark: Neo4j vs default (SQLite)

Dataset: 10000 nodes, 50000 edges. Repeats: 5. Depths: 2, 3, 4, 5.

Baseline: sqlite (StorageBackend kg_edges; production per-node BFS reachable-set, the GraphRetriever path recall actually uses).

The default (SQLite) traversal cost is the production graph stage: a Python-side reachable-set BFS that issues one `get_kg_edges_from` / `get_kg_node_by_id` call per visited node over the indexed `kg_edges` table (the `GraphRetriever` path recall actually uses), not the rarely-used `traverse_kg`. SQLite has no native shortest-path operator, so its shortest-path figure is a Python BFS over `get_kg_edges_from` — the work the default path must do to answer a path query. The `*_ids_*` rows return only the reachable node-id set (what recall scores), isolating traversal cost from full-object serialization.

| Query | SQLite median (ms) | SQLite p95 (ms) | Neo4j median (ms) | Neo4j p95 (ms) | Speedup (SQLite/Neo4j) |
|---|---|---|---|---|---|
| single_hop | 5.702 | 16.771 | 97.02 | 292.797 | 0.06x |
| traverse_depth_2 | 0.107 | 0.11 | 9.212 | 10.803 | 0.01x |
| traverse_depth_3 | 0.484 | 0.513 | 11.047 | 20.828 | 0.04x |
| traverse_depth_4 | 2.391 | 2.56 | 25.245 | 29.315 | 0.09x |
| traverse_depth_5 | 9.494 | 9.701 | 82.646 | 106.151 | 0.11x |
| traverse_hub_depth_3 | 80.194 | 80.5 | 329.419 | 351.578 | 0.24x |
| traverse_hub_depth_4 | 169.407 | 169.836 | 418.266 | 620.538 | 0.41x |
| traverse_hub_depth_5 | 194.013 | 219.007 | 421.778 | 441.795 | 0.46x |
| traverse_hub_ids_depth_3 | 82.189 | 101.532 | 233.604 | 235.251 | 0.35x |
| traverse_hub_ids_depth_4 | 169.774 | 170.041 | 285.881 | 289.598 | 0.59x |
| traverse_hub_ids_depth_5 | 193.262 | 204.561 | 290.707 | 310.033 | 0.66x |
| shortest_path | 122.869 | 133.127 | 57.552 | 62.262 | 2.13x |

## SC-003 (>= 5x faster at depth 3+ and shortest path)

- traverse_depth_3: 0.04x FAIL
- traverse_depth_4: 0.09x FAIL
- traverse_depth_5: 0.11x FAIL
- traverse_hub_depth_3: 0.24x FAIL
- traverse_hub_depth_4: 0.41x FAIL
- traverse_hub_depth_5: 0.46x FAIL
- shortest_path: 2.13x FAIL

Verdict: NOT MET.
