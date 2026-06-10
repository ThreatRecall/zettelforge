# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import patch

from zettelforge import osint as _osint  # noqa: F401 -- side effects
from zettelforge.knowledge_graph import KnowledgeGraph
from zettelforge.osint import entity_resolver
from zettelforge.osint.collectors.infrastructure import bgp_collector
from zettelforge.osint.executor import run_osint_collection
from zettelforge.osint.transform_registry import (
    CollectorTuple,
    TransformMetadata,
    TransformRegistry,
)


def _fake_dns_collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    assert input_entity_type == 'DomainName'
    assert input_value == 'example.com'
    return [
        CollectorTuple(
            output_entity_type='IPv4Address',
            output_value='1.2.3.4',
            edge_type='resolves_to',
            from_entity_type='DomainName',
            to_entity_type='IPv4Address',
            output_props={'value': '1.2.3.4'},
            edge_props={'source': 'unit-test'},
        )
    ]


def _boom_collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    raise RuntimeError('collector boom')


def test_run_osint_collection_persists_nodes_and_edges(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(entity_resolver, '_ALIAS_INDEX', {})
    monkeypatch.setattr(entity_resolver, '_ALIAS_REVERSE', {})

    kg = KnowledgeGraph(data_dir=str(tmp_path))
    registry = TransformRegistry()
    registry.register(
        TransformMetadata(
            name='fake_dns',
            description='Fake DNS collector for executor tests.',
            input_types=('DomainName',),
            output_types=(('IPv4Address', 'resolves_to'),),
        ),
        _fake_dns_collect,
    )

    result = run_osint_collection('DomainName', 'Example.COM.', kg=kg, registry=registry)

    assert result.collectors_run == ['fake_dns']
    assert result.canonical_input_value == 'example.com'
    assert result.error_count == 0
    assert result.persisted_count == 1
    assert result.seed_node_id is not None
    assert result.persisted[0].output_value == '1.2.3.4'

    seed = kg.get_node('DomainName', 'example.com')
    target = kg.get_node('IPv4Address', '1.2.3.4')
    assert seed is not None
    assert target is not None

    neighbors = kg.get_neighbors('DomainName', 'example.com', 'resolves_to')
    assert [item['node']['entity_value'] for item in neighbors] == ['1.2.3.4']


def test_run_osint_collection_records_nonfatal_collector_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(entity_resolver, '_ALIAS_INDEX', {})
    monkeypatch.setattr(entity_resolver, '_ALIAS_REVERSE', {})

    kg = KnowledgeGraph(data_dir=str(tmp_path))
    registry = TransformRegistry()
    registry.register(
        TransformMetadata(
            name='boom',
            description='Failing collector used to verify fail-closed handling.',
            input_types=('DomainName',),
            output_types=(('IPv4Address', 'resolves_to'),),
        ),
        _boom_collect,
    )
    registry.register(
        TransformMetadata(
            name='fake_dns',
            description='Fake DNS collector for executor tests.',
            input_types=('DomainName',),
            output_types=(('IPv4Address', 'resolves_to'),),
        ),
        _fake_dns_collect,
    )

    result = run_osint_collection('DomainName', 'example.com', kg=kg, registry=registry)

    assert result.collectors_run == ['boom', 'fake_dns']
    assert result.error_count == 1
    assert result.errors[0].collector_name == 'boom'
    assert result.persisted_count == 1
    assert result.tuples_collected == 1


def test_run_osint_collection_respects_empty_allowlist(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(entity_resolver, '_ALIAS_INDEX', {})
    monkeypatch.setattr(entity_resolver, '_ALIAS_REVERSE', {})

    kg = KnowledgeGraph(data_dir=str(tmp_path))
    registry = TransformRegistry()
    registry.register(
        TransformMetadata(
            name='fake_dns',
            description='Fake DNS collector for executor tests.',
            input_types=('DomainName',),
            output_types=(('IPv4Address', 'resolves_to'),),
        ),
        _fake_dns_collect,
    )

    result = run_osint_collection(
        'DomainName',
        'example.com',
        kg=kg,
        registry=registry,
        collector_names=[],
    )

    assert result.collectors_run == []
    assert result.tuples_collected == 0
    assert result.error_count == 0
    assert result.persisted_count == 0
    assert result.seed_node_id is not None
    assert kg.get_neighbors('DomainName', 'example.com', 'resolves_to') == []


def _invalid_endpoint_collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    return [
        CollectorTuple(
            output_entity_type='Organization',
            output_value='Example Corp',
            edge_type='owned_by',
            from_entity_type='Netblock',
            to_entity_type='Organization',
            output_props={'name': 'Example Corp'},
            edge_props={'cidr': 'not-a-cidr'},
        )
    ]


def _typo_relation_collect(input_entity_type: str, input_value: str) -> list[CollectorTuple]:
    return [
        CollectorTuple(
            output_entity_type='IPv4Address',
            output_value='1.2.3.4',
            edge_type='reslove_to',
            from_entity_type='DomainName',
            to_entity_type='IPv4Address',
            output_props={'value': '1.2.3.4'},
            edge_props={},
        )
    ]


def test_run_osint_collection_does_not_persist_partial_tuple_on_invalid_endpoint(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(entity_resolver, '_ALIAS_INDEX', {})
    monkeypatch.setattr(entity_resolver, '_ALIAS_REVERSE', {})

    kg = KnowledgeGraph(data_dir=str(tmp_path))
    registry = TransformRegistry()
    registry.register(
        TransformMetadata(
            name='invalid_endpoint',
            description='Collector that emits an invalid endpoint payload.',
            input_types=('ASNumber',),
            output_types=(('Organization', 'owned_by'),),
        ),
        _invalid_endpoint_collect,
    )

    result = run_osint_collection('ASNumber', 'AS15169', kg=kg, registry=registry)

    assert result.collectors_run == ['invalid_endpoint']
    assert result.error_count == 1
    assert result.persisted_count == 0  # seed writes are not counted in the result
    assert result.seed_node_id is not None
    assert kg.get_node('Organization', 'example corp') is None
    assert kg.get_neighbors('ASNumber', '15169', 'owned_by') == []


def test_run_osint_collection_validates_endpoints_in_dry_run(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(entity_resolver, '_ALIAS_INDEX', {})
    monkeypatch.setattr(entity_resolver, '_ALIAS_REVERSE', {})

    kg = KnowledgeGraph(data_dir=str(tmp_path))
    registry = TransformRegistry()
    registry.register(
        TransformMetadata(
            name='invalid_endpoint',
            description='Collector that emits an invalid endpoint payload.',
            input_types=('ASNumber',),
            output_types=(('Organization', 'owned_by'),),
        ),
        _invalid_endpoint_collect,
    )

    result = run_osint_collection(
        'ASNumber',
        'AS15169',
        kg=kg,
        registry=registry,
        persist=False,
    )

    assert result.collectors_run == ['invalid_endpoint']
    assert result.error_count == 1
    assert result.persisted_count == 0
    assert result.seed_node_id is None
    assert kg.get_node('Organization', 'example corp') is None
    assert kg.get_neighbors('ASNumber', '15169', 'owned_by') == []


def test_run_osint_collection_rejects_unregistered_relation_even_when_metadata_matches(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(entity_resolver, '_ALIAS_INDEX', {})
    monkeypatch.setattr(entity_resolver, '_ALIAS_REVERSE', {})

    kg = KnowledgeGraph(data_dir=str(tmp_path))
    registry = TransformRegistry()
    registry.register(
        TransformMetadata(
            name='typo_relation',
            description='Collector that emits a typo relation.',
            input_types=('DomainName',),
            output_types=(('IPv4Address', 'reslove_to'),),
        ),
        _typo_relation_collect,
    )

    result = run_osint_collection('DomainName', 'example.com', kg=kg, registry=registry)

    assert result.collectors_run == ['typo_relation']
    assert result.error_count == 1
    assert result.persisted_count == 0
    assert result.seed_node_id is not None
    assert kg.get_neighbors('DomainName', 'example.com', 'reslove_to') == []


def test_bgp_collector_emits_netblocks_from_asn() -> None:
    payload = {
        'owner': {'name': 'Google LLC'},
        'prefixes': [
            {'prefix': '8.8.8.0/24'},
            {'prefix': '8.8.4.0/24'},
            {'prefix': 'invalid'},
        ],
    }
    with patch.object(bgp_collector, '_bgpview_get', return_value=payload):
        out = bgp_collector.collect('ASNumber', 'AS15169')

    assert [item.output_value for item in out] == ['8.8.8.0/24', '8.8.4.0/24']
    assert all(item.from_entity_type == 'Netblock' for item in out)
    assert all(item.to_entity_type == 'ASNumber' for item in out)
    assert all(item.output_props['org'] == 'Google LLC' for item in out)
