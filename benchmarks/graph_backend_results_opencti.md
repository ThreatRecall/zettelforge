# Graph backend benchmark: Neo4j vs default (SQLite) on REAL OpenCTI data

Dataset: 7481 nodes, 35073 edges. Repeats: 7. Depths: 2, 3, 4, 5.

Baseline: sqlite (StorageBackend kg_edges; production per-node BFS reachable-set, the GraphRetriever path recall actually uses).

## Real graph characteristics

Source: live OpenCTI instance (read-only OpenSearch scroll). Avg degree 9.38, max total degree 602, max out-degree 191. Node identity = OpenCTI internal_id (real topology preserved exactly).

Forward-traversal hub probe (highest OUT-degree): Kimsuky (out-degree 191, total degree 191). Note: the highest *total*-degree nodes in real CTI data are MITRE techniques, which are pure sinks (hundreds of incoming `uses`, zero outgoing); a forward traversal from them visits nothing, so the traversal probe uses the highest out-degree node (a malware / intrusion-set that `uses` many techniques).

Top hub entities by total degree:

| Entity | Type | Total degree | Out-degree |
|---|---|---|---|
| [T1059] Command and Scripting Interpreter | Attack-Pattern | 602 | 0 |
| [T1027] Obfuscated Files or Information | Attack-Pattern | 509 | 0 |
| [T1105] Ingress Tool Transfer | Attack-Pattern | 487 | 0 |
| [T1071] Application Layer Protocol | Attack-Pattern | 451 | 0 |
| [T1082] System Information Discovery | Attack-Pattern | 409 | 0 |
| [T1071.001] Web Protocols | Attack-Pattern | 401 | 1 |
| [T1059.003] Windows Command Shell | Attack-Pattern | 370 | 1 |
| [T1083] File and Directory Discovery | Attack-Pattern | 356 | 0 |
| [T1070] Indicator Removal | Attack-Pattern | 347 | 0 |
| [T1140] Deobfuscate/Decode Files or Information | Attack-Pattern | 336 | 0 |

Top hub entities by out-degree (the real forward-traversal hubs):

| Entity | Type | Out-degree | Total degree |
|---|---|---|---|
| Kimsuky | Intrusion-Set | 191 | 191 |
| Windows | Infrastructure | 172 | 173 |
| Windows | Software | 172 | 172 |
| APT28 | Intrusion-Set | 159 | 159 |
| Lazarus Group | Intrusion-Set | 155 | 155 |
| APT41 | Intrusion-Set | 147 | 147 |
| APT29 | Intrusion-Set | 145 | 145 |
| Sandworm Team | Intrusion-Set | 143 | 143 |
| OilRig | Intrusion-Set | 138 | 138 |
| Mustang Panda | Intrusion-Set | 137 | 137 |

Shortest-path probe pairs: 10 pairs at undirected graph distance 3-6 (median 5). These are genuinely indirectly connected real entities, not adjacent ones.

The default (SQLite) traversal cost is the production graph stage: a Python-side reachable-set BFS that issues one `get_kg_edges_from` / `get_kg_node_by_id` call per visited node over the indexed `kg_edges` table (the `GraphRetriever` path recall actually uses), not the rarely-used `traverse_kg`. SQLite has no native shortest-path operator, so its shortest-path figure is a Python BFS over `get_kg_edges_from` — the work the default path must do to answer a path query. The `*_ids_*` rows return only the reachable node-id set (what recall scores), isolating traversal cost from full-object serialization.

| Query | SQLite median (ms) | SQLite p95 (ms) | Neo4j median (ms) | Neo4j p95 (ms) | Speedup (SQLite/Neo4j) | Result size (SQLite / Neo4j) |
|---|---|---|---|---|---|---|
| single_hop | 1.29 | 1.964 | 18.388 | 26.207 | 0.07x | 191 / 191 |
| traverse_depth_2 | 2.482 | 2.637 | 17.541 | 18.387 | 0.14x | 247 / 247 |
| traverse_depth_3 | 2.626 | 2.786 | 16.091 | 16.734 | 0.16x | 247 / 247 |
| traverse_depth_4 | 2.596 | 2.779 | 17.295 | 18.251 | 0.15x | 247 / 247 |
| traverse_depth_5 | 2.719 | 2.85 | 16.924 | 28.864 | 0.16x | 247 / 247 |
| traverse_hub_depth_3 | 2.734 | 2.887 | 14.942 | 16.496 | 0.18x | 247 / 247 |
| traverse_hub_depth_4 | 2.822 | 2.955 | 16.437 | 18.822 | 0.17x | 247 / 247 |
| traverse_hub_depth_5 | 2.78 | 2.941 | 15.946 | 17.46 | 0.17x | 247 / 247 |
| traverse_hub_ids_depth_3 | 2.758 | 2.904 | 13.084 | 13.349 | 0.21x | 247 / 247 |
| traverse_hub_ids_depth_4 | 2.794 | 2.924 | 13.301 | 13.752 | 0.21x | 247 / 247 |
| traverse_hub_ids_depth_5 | 2.773 | 2.921 | 12.658 | 13.028 | 0.22x | 247 / 247 |
| shortest_path_directed | 5.768 | 5.804 | 56.361 | 63.158 | 0.1x | 3 / 9 |
| shortest_path_undirected | 752.056 | 762.611 | 37.665 | 54.117 | 19.97x | 9 / 9 |

Speedup = SQLite median / Neo4j median: a value < 1 means SQLite is faster (Neo4j slower by 1/ratio); a value >= 5 means Neo4j is >= 5x faster (the SC-003 target). `shortest_path_directed` is the production default (outgoing-only) BFS and finds fewer paths on real CTI data, so its result size is smaller than Neo4j's undirected count; `shortest_path_undirected` walks both directions for an identical question (matched sizes) and is the apples-to-apples path comparison.

## SC-003 (>= 5x faster at depth 3+ and shortest path)

- traverse_depth_3: 0.16x FAIL
- traverse_depth_4: 0.15x FAIL
- traverse_depth_5: 0.16x FAIL
- traverse_hub_depth_3: 0.18x FAIL
- traverse_hub_depth_4: 0.17x FAIL
- traverse_hub_depth_5: 0.17x FAIL
- shortest_path_undirected: 19.97x PASS

Verdict: NOT MET.
