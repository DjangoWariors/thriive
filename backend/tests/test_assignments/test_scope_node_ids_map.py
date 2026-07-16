"""scope_node_ids_map — the batched ownership resolver must agree exactly with
the per-entity scope_node_ids_for_entity across dates, roles and both internal
branches (per-scope prefix queries vs the streamed full-node pass).
"""
from datetime import date, timedelta

import pytest

from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType

TODAY = date.today()


@pytest.fixture
def world(db):
    """Two owners with nested + disjoint scopes, one past owner, one unassigned."""
    et = NodeType.objects.create(name='ASM', code='ASM', level_order=3, effective_from=TODAY)
    gt = GeographyType.objects.create(name='Geo', code='geo', levels=['nation', 'town', 'outlet'])

    nation = GeographyNode.objects.create(geography_type=gt, name='India', code='IN', level='nation')
    town_a = GeographyNode.objects.create(geography_type=gt, name='Town A', code='TA', level='town', parent=nation)
    town_b = GeographyNode.objects.create(geography_type=gt, name='Town B', code='TB', level='town', parent=nation)
    out_a1 = GeographyNode.objects.create(geography_type=gt, name='Out A1', code='OA1', level='outlet', parent=town_a)
    out_b1 = GeographyNode.objects.create(geography_type=gt, name='Out B1', code='OB1', level='outlet', parent=town_b)

    anjali = Node.objects.create(entity_type=et, name='Anjali', code='ASM-0001', effective_from=TODAY)
    ravi = Node.objects.create(entity_type=et, name='Ravi', code='ASM-0002', effective_from=TODAY)
    idle = Node.objects.create(entity_type=et, name='Idle', code='ASM-0003', effective_from=TODAY)

    Assignment.objects.create(assignee=anjali, scope=town_a, role_in_scope='owner',
                              effective_from=TODAY - timedelta(days=30))
    # Nested: Anjali also directly owns an outlet inside her own town.
    Assignment.objects.create(assignee=anjali, scope=out_a1, role_in_scope='owner',
                              effective_from=TODAY - timedelta(days=30))
    Assignment.objects.create(assignee=ravi, scope=town_b, role_in_scope='owner',
                              effective_from=TODAY - timedelta(days=30))
    # Ravi ALSO stood in for Town A last month only.
    Assignment.objects.create(assignee=ravi, scope=town_a, role_in_scope='stand_in',
                              effective_from=TODAY - timedelta(days=60),
                              effective_to=TODAY - timedelta(days=31))
    return {
        'entities': [anjali.pk, ravi.pk, idle.pk],
        'nodes': {'nation': nation, 'town_a': town_a, 'town_b': town_b,
                  'out_a1': out_a1, 'out_b1': out_b1},
    }


def _assert_map_matches_single(entity_ids, on=None, role=None):
    batched = AssignmentService.scope_node_ids_map(entity_ids, on=on, role=role)
    for eid in entity_ids:
        single = sorted(AssignmentService.scope_node_ids_for_entity(eid, on=on, role=role))
        assert batched[eid] == single, f'entity {eid} diverged (on={on}, role={role})'


@pytest.mark.django_db
def test_map_equals_single_today(world):
    _assert_map_matches_single(world['entities'])


@pytest.mark.django_db
def test_map_equals_single_as_of_past_date(world):
    _assert_map_matches_single(world['entities'], on=TODAY - timedelta(days=45))


@pytest.mark.django_db
def test_map_equals_single_role_filtered(world):
    _assert_map_matches_single(world['entities'], role='owner')
    _assert_map_matches_single(world['entities'], on=TODAY - timedelta(days=45), role='stand_in')


@pytest.mark.django_db
def test_streamed_branch_equals_single(world, monkeypatch):
    # Force the many-scopes branch (full node stream + ancestor-prefix decompose).
    monkeypatch.setattr(AssignmentService, '_BATCH_SCOPE_THRESHOLD', 0)
    _assert_map_matches_single(world['entities'])
    _assert_map_matches_single(world['entities'], on=TODAY - timedelta(days=45))


@pytest.mark.django_db
def test_entity_without_territory_maps_to_empty(world):
    result = AssignmentService.scope_node_ids_map(world['entities'])
    idle = world['entities'][2]
    assert result[idle] == []


@pytest.mark.django_db
def test_constant_query_count(world, django_assert_max_num_queries):
    with django_assert_max_num_queries(4):
        AssignmentService.scope_node_ids_map(world['entities'])


@pytest.mark.django_db
def test_scope_node_qs_matches_id_list(world):
    for eid in world['entities']:
        ids = sorted(AssignmentService.scope_node_ids_for_entity(eid))
        qs = AssignmentService.scope_node_qs_for_entity(eid)
        if not ids:
            assert qs is None
        else:
            assert sorted(v['id'] for v in qs) == ids
