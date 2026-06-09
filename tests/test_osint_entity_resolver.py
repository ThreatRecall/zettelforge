# ruff: noqa: S101

from __future__ import annotations

import pytest

from zettelforge import osint as _osint  # noqa: F401 -- side effects
from zettelforge.knowledge_graph import KnowledgeGraph
from zettelforge.osint import entity_resolver


def test_add_resolved_registers_alias_for_existing_node(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(entity_resolver, '_ALIAS_INDEX', {})
    monkeypatch.setattr(entity_resolver, '_ALIAS_REVERSE', {})

    kg = KnowledgeGraph(data_dir=str(tmp_path))
    node_id, created = entity_resolver.add_resolved(
        kg,
        'DomainName',
        'example.com',
        {'value': 'example.com'},
    )
    assert created is True

    resolved_id, created_again = entity_resolver.add_resolved(
        kg,
        'DomainName',
        'Example.COM.',
        {'value': 'example.com', 'source': 'unit-test'},
    )
    assert resolved_id == node_id
    assert created_again is False
    assert kg._osint_alias_reverse['Example.COM.'] == 'DomainName:example.com'
    assert entity_resolver.resolve('DomainName', 'Example.COM.', kg=kg) == node_id

    node = kg.get_node('DomainName', 'example.com')
    assert node is not None
    assert node['properties']['value'] == 'example.com'
    assert node['properties']['source'] == 'unit-test'

    reloaded = KnowledgeGraph(data_dir=str(tmp_path))
    reloaded_node = reloaded.get_node('DomainName', 'example.com')
    assert reloaded_node is not None
    assert reloaded_node['properties']['source'] == 'unit-test'


def test_canonicalise_organization_normalizes_case_and_whitespace() -> None:
    assert entity_resolver.canonicalise_value('Organization', ' Example  Corp ') == 'example corp'


@pytest.mark.parametrize(
    ('entity_type', 'raw', 'expected'),
    [
        ('URL', 'HTTPS://Example.com/path', 'https://example.com/path'),
        ('Website', 'HTTP://Example.com', 'http://example.com/'),
        ('NSRecord', 'NS1.Example.com.', 'ns1.example.com'),
        ('MXRecord', '10 MX.Example.com.', '10 mx.example.com'),
        ('Port', '443/TCp', '443/tcp'),
        ('WebTitle', 'HTTPS://Example.com/:: Title ', 'https://example.com/::Title'),
    ],
)
def test_canonicalise_value_covers_common_osint_node_shapes(
    entity_type: str,
    raw: str,
    expected: str,
) -> None:
    assert entity_resolver.canonicalise_value(entity_type, raw) == expected


def test_add_resolved_scopes_aliases_to_each_knowledge_graph(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(entity_resolver, '_ALIAS_INDEX', {})
    monkeypatch.setattr(entity_resolver, '_ALIAS_REVERSE', {})

    kg_one = KnowledgeGraph(data_dir=str(tmp_path / 'one'))
    kg_two = KnowledgeGraph(data_dir=str(tmp_path / 'two'))

    node_one, created_one = entity_resolver.add_resolved(kg_one, 'DomainName', 'example.com')
    node_two, created_two = entity_resolver.add_resolved(kg_two, 'DomainName', 'example.com')

    assert created_one is True
    assert created_two is True
    assert node_one != node_two
    assert entity_resolver.resolve('DomainName', 'example.com', kg=kg_one) == node_one
    assert entity_resolver.resolve('DomainName', 'example.com', kg=kg_two) == node_two
