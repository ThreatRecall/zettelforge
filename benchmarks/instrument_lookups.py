#!/usr/bin/env python3
"""Instrument note-lookup volume per recall stage.

Counts store.get_note_by_id calls (total vs unique ids) and graph result
sizes per query to locate the redundant-lookup source the profiler exposed
(~476 lookups/query on an 8-note corpus).

Usage:
  python benchmarks/instrument_lookups.py
"""
import os
import tempfile

os.environ.setdefault('ZETTELFORGE_ENRICHMENT_ENABLED', 'false')

from cti_retrieval_benchmark import CTI_QUERIES, CTI_REPORTS

from zettelforge import MemoryManager
from zettelforge.graph_retriever import GraphRetriever


def main() -> None:
    tmpdir = tempfile.mkdtemp(prefix='instr_lookups_')
    mm = MemoryManager(jsonl_path=f'{tmpdir}/notes.jsonl', lance_path=f'{tmpdir}/vectordb')
    for report in CTI_REPORTS:
        mm.remember(report['content'], source_type='threat_report', source_ref=report['id'], domain='cti')

    # Wrap get_note_by_id with a counter
    calls = {'total': 0, 'ids': []}
    orig = mm.store.get_note_by_id

    def counting(nid):
        calls['total'] += 1
        calls['ids'].append(nid)
        return orig(nid)

    mm.store.get_note_by_id = counting

    # Wrap graph retrieval to report result sizes
    orig_retrieve = GraphRetriever.retrieve_note_ids
    graph_sizes = []

    def counting_retrieve(self, query_entities, max_depth=2):
        res = orig_retrieve(self, query_entities, max_depth=max_depth)
        graph_sizes.append(len(res))
        return res

    GraphRetriever.retrieve_note_ids = counting_retrieve

    print(f'{"query":<48} {"lookups":>8} {"unique":>7} {"graph_n":>8}')
    for qa in CTI_QUERIES:
        calls['total'] = 0
        calls['ids'] = []
        graph_sizes.clear()
        mm.recall(qa['question'], k=10, exclude_superseded=False)
        uniq = len(set(calls['ids']))
        gsz = graph_sizes[0] if graph_sizes else 0
        print(f'{qa["question"][:46]:<48} {calls["total"]:>8} {uniq:>7} {gsz:>8}')


if __name__ == '__main__':
    main()
