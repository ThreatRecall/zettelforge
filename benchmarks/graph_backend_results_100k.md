# Graph backend benchmark: Neo4j vs default (SQLite)

Dataset: 100000 nodes, 600000 edges. Repeats: 3. Depths: 2, 3, 4, 5.

Baseline: sqlite (StorageBackend kg_edges; production per-node BFS reachable-set, the GraphRetriever path recall actually uses).

The default (SQLite) path is the production traversal store (`traverse_kg` / `get_kg_neighbors` over the indexed `kg_edges` table). SQLite has no native shortest-path operator, so its shortest-path figure is a Python BFS over `get_kg_edges_from` — the work the default path must do to answer a path query.

| Query | SQLite median (ms) | SQLite p95 (ms) | Neo4j median (ms) | Neo4j p95 (ms) | Speedup (SQLite/Neo4j) |
|---|---|---|---|---|---|
| single_hop | 17.497 | 28.324 | 95.367 | 129.685 | 0.18x |
| traverse_depth_2 | 0.164 | 0.483 | 13.046 | 72.881 | 0.01x |
| traverse_depth_3 | 1.112 | 1.757 | 19.27 | 19.398 | 0.06x |
| traverse_depth_4 | 7.856 | 8.42 | 67.722 | 69.502 | 0.12x |
| traverse_depth_5 | 43.092 | 68.807 | 322.59 | 357.679 | 0.13x |
| traverse_hub_depth_3 | 170.755 | 201.383 | 1015.226 | 1183.297 | 0.17x |
| traverse_hub_depth_4 | 1113.097 | 1152.251 | 3246.047 | 3404.9 | 0.34x |
| traverse_hub_depth_5 | 4428.802 | 4430.388 | 4544.456 | 4600.856 | 0.97x |
| traverse_hub_ids_depth_3 | 161.886 | 162.387 | 663.154 | 707.378 | 0.24x |
| traverse_hub_ids_depth_4 | 1129.075 | 1130.036 | 2066.841 | 2077.127 | 0.55x |
| traverse_hub_ids_depth_5 | 4632.272 | 4659.628 | 2884.661 | 2898.508 | 1.61x |
| shortest_path | 322.08 | 443.758 | 50.541 | 179.924 | 6.37x |

## SC-003 (>= 5x faster at depth 3+ and shortest path)

- traverse_depth_3: 0.06x FAIL
- traverse_depth_4: 0.12x FAIL
- traverse_depth_5: 0.13x FAIL
- traverse_hub_depth_3: 0.17x FAIL
- traverse_hub_depth_4: 0.34x FAIL
- traverse_hub_depth_5: 0.97x FAIL
- shortest_path: 6.37x PASS

Verdict: NOT MET.
