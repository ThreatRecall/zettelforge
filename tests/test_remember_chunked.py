"""remember_chunked splits long content on sentence boundaries into bounded chunks.

Restores the chunked-ingestion API the CTI benchmark exercises and the
MemPalace comparison identified as the conversational-granularity lever.
"""

import pytest

from zettelforge.config import reload_config


@pytest.fixture(autouse=True)
def _no_enrichment(monkeypatch):
    monkeypatch.setenv('ZETTELFORGE_ENRICHMENT_ENABLED', 'false')
    reload_config()
    yield
    reload_config()


def _manager(tmp_path):
    from zettelforge.memory_manager import MemoryManager

    return MemoryManager(
        jsonl_path=str(tmp_path / 'notes.jsonl'),
        lance_path=str(tmp_path / 'vec'),
    )


def test_remember_chunked_splits_and_stores(tmp_path):
    mm = _manager(tmp_path)
    content = ' '.join(f'Sentence number {i} about APT28 operations.' for i in range(60))
    notes = mm.remember_chunked(
        content,
        source_type='threat_report',
        source_ref='r1',
        domain='cti',
        chunk_size=800,
    )
    assert len(notes) >= 2
    assert all(len(n.content.raw) <= 900 for n in notes)
    assert mm.store.count_notes() == len(notes)
    # Chunks carry an ordinal source_ref so provenance survives the split
    refs = [n.content.source_ref for n in notes]
    assert refs == [f'r1#c{i}' for i in range(len(notes))]


def test_remember_chunked_short_content_single_note(tmp_path):
    mm = _manager(tmp_path)
    notes = mm.remember_chunked(
        'Short note.',
        source_type='threat_report',
        source_ref='r1',
        domain='cti',
        chunk_size=800,
    )
    assert len(notes) == 1
    assert notes[0].content.source_ref == 'r1'


def test_remember_chunked_never_drops_text(tmp_path):
    mm = _manager(tmp_path)
    content = ' '.join(f'Fact {i} is recorded here.' for i in range(120))
    notes = mm.remember_chunked(
        content,
        source_type='conversation',
        source_ref='s1',
        domain='general',
        chunk_size=400,
    )
    rebuilt = ' '.join(n.content.raw for n in notes)
    for i in range(120):
        assert f'Fact {i} is recorded here.' in rebuilt
