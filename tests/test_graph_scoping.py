"""Recall's graph stage must read the per-store KG, not the process-global one.

_update_knowledge_graph writes MENTIONED_IN edges to the manager's storage
backend (scoped SQLite). Before this fix, _recall_inner traversed the
process-global JSONL KG instead: isolated stores saw thousands of phantom
note nodes from other stores (latency) and never saw their own graph
(dead graph signal).
"""

import pytest

from zettelforge.config import reload_config


@pytest.fixture(autouse=True)
def _no_enrichment(monkeypatch):
    monkeypatch.setenv('ZETTELFORGE_ENRICHMENT_ENABLED', 'false')
    reload_config()
    yield
    reload_config()


def _manager(tmp_path, sub):
    from zettelforge.memory_manager import MemoryManager

    d = tmp_path / sub
    d.mkdir()
    return MemoryManager(jsonl_path=str(d / 'notes.jsonl'), lance_path=str(d / 'vec'))


def test_backend_get_kg_edges_from(tmp_path):
    mm = _manager(tmp_path, 'a')
    mm.store.add_kg_edge('actor', 'APT28', 'note', 'n1', 'MENTIONED_IN')
    node = mm.store.get_kg_node('actor', 'APT28')
    assert node is not None
    edges = mm.store.get_kg_edges_from(node['node_id'])
    assert len(edges) == 1
    target = mm.store.get_kg_node_by_id(edges[0]['to_node_id'])
    assert target['entity_type'] == 'note'
    assert target['entity_value'] == 'n1'


def test_graph_retriever_sees_own_store_writes(tmp_path):
    from zettelforge.graph_retriever import GraphRetriever, StoreGraphSource

    mm = _manager(tmp_path, 'a')
    note, _ = mm.remember(
        'APT28 used the DROPBEAR backdoor to target NATO members.',
        source_type='threat_report',
        source_ref='r1',
        domain='cti',
    )
    # Mirror _recall_inner's entity resolution for the query
    query_entities = mm.indexer.extractor.extract_all('What does APT28 use?')
    resolved = {
        etype: [mm.resolver.resolve(etype, e) for e in elist]
        for etype, elist in query_entities.items()
    }
    assert any(resolved.values()), 'extractor should find APT28 in the query'

    retriever = GraphRetriever(StoreGraphSource(mm.store))
    results = retriever.retrieve_note_ids(query_entities=resolved, max_depth=2)
    assert any(r.note_id == note.id for r in results)


def test_recall_graph_isolated_between_stores(tmp_path):
    mm_a = _manager(tmp_path, 'a')
    mm_a.remember(
        'APT28 used the DROPBEAR backdoor to target NATO members.',
        source_type='threat_report',
        source_ref='r1',
        domain='cti',
    )

    mm_b = _manager(tmp_path, 'b')
    mm_b.remember(
        'The weather in Toronto stayed mild through October.',
        source_type='conversation',
        source_ref='s1',
        domain='general',
    )

    lookups = {'n': 0}
    orig = mm_b.store.get_note_by_id

    def counting(nid):
        lookups['n'] += 1
        return orig(nid)

    mm_b.store.get_note_by_id = counting
    results = mm_b.recall('What does APT28 use?', k=10, exclude_superseded=False)

    # Store B has one note; the graph stage must not import thousands of
    # phantom candidates from store A or the global KG.
    assert lookups['n'] <= 10
    assert all('APT28' not in n.content.raw for n in results)


def test_high_fanout_entities_skip_graph_stage(tmp_path):
    """Entities mapping to a large share of the corpus carry no signal
    (conversational speaker names): they must not flood blended recall."""
    from zettelforge.graph_retriever import GraphRetriever, StoreGraphSource

    mm = _manager(tmp_path, 'fanout')
    for i in range(12):
        mm.remember(
            f'Melanie: session {i} chat about topic {i} with details.',
            source_type='dialogue',
            source_ref=f's{i}',
            domain='locomo',
        )
    mm.remember(
        'Melanie: I tried the DROPBEAR exploit demo today.',
        source_type='dialogue',
        source_ref='s99',
        domain='locomo',
    )

    filtered = mm._filter_low_signal_entities(
        {'person': ['melanie'], 'tool': ['dropbear']}, max_fanout=5
    )
    assert filtered.get('person', []) == []
    assert filtered.get('tool') == ['dropbear']

    # End to end: recall must not return only melanie-flooded results when
    # the query names a discriminative entity.
    results = mm.recall('What is the DROPBEAR exploit?', k=5, exclude_superseded=False)
    assert any('DROPBEAR' in n.content.raw for n in results)
