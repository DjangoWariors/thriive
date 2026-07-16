"""
Channel + Geography enterprise behaviour:
  - channel deactivate guard (blocks when entities/types reference it)
  - geography level validation (bad level / wrong-type parent / inverted level)
  - GeographyNodeService.move recomputes every descendant path + audits + rejects cycles
  - geography type/node deactivate guards
  - Node detail serializer emits nested channel/geography objects
"""
from datetime import date, timedelta

import pytest

from apps.audit.models import AuditLog
from apps.core.exceptions import BusinessError
from apps.hierarchy.config_services import (
    ChannelService,
    GeographyNodeService,
    GeographyTypeService,
)
from apps.hierarchy.models import Channel, Node, NodeType, GeographyNode, GeographyType


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def channel(db):
    return Channel.objects.create(code='GT', name='General Trade')


@pytest.fixture
def geo_type(db):
    return GeographyType.objects.create(
        name='Sales Geo', code='sales_geo',
        levels=['region', 'state', 'district', 'town'],
    )


@pytest.fixture
def outlet_type(db):
    return NodeType.objects.create(
        name='Outlet', code='outlet', level_order=1, effective_from=date.today(),
    )


# ── Channel guards ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestChannelGuards:
    def test_duplicate_code_rejected(self, channel):
        with pytest.raises(BusinessError, match='already exists'):
            ChannelService.create({'code': 'GT', 'name': 'Dup'})

    def test_deactivate_blocked_when_entity_uses_it(self, channel, outlet_type):
        Node.objects.create(
            entity_type=outlet_type, name='Shop', code='shop1',
            channel=channel, effective_from=date.today(),
        )
        with pytest.raises(BusinessError, match='still used by'):
            ChannelService.deactivate(channel)
        channel.refresh_from_db()
        assert channel.is_active is True

    def test_deactivate_blocked_when_entity_type_uses_it(self, channel):
        NodeType.objects.create(
            name='MT Distributor', code='mt_dist', level_order=2,
            effective_from=date.today(), channel=channel,
        )
        with pytest.raises(BusinessError, match='still used by'):
            ChannelService.deactivate(channel)

    def test_deactivate_succeeds_when_unused(self, channel):
        ChannelService.deactivate(channel)
        channel.refresh_from_db()
        assert channel.is_active is False


# ── Geography level validation ──────────────────────────────────────────────────

@pytest.mark.django_db
class TestGeoValidation:
    def test_bad_level_rejected(self, geo_type):
        with pytest.raises(BusinessError, match='not defined'):
            GeographyNodeService.create({
                'geography_type': geo_type, 'name': 'X', 'code': 'X',
                'level': 'galaxy', 'parent': None,
            })

    def test_child_must_be_deeper_than_parent(self, geo_type):
        region = GeographyNodeService.create({
            'geography_type': geo_type, 'name': 'North', 'code': 'N',
            'level': 'region', 'parent': None,
        })
        # A second 'region' cannot sit under a 'region'.
        with pytest.raises(BusinessError, match='must sit below'):
            GeographyNodeService.create({
                'geography_type': geo_type, 'name': 'North2', 'code': 'N2',
                'level': 'region', 'parent': region,
            })

    def test_parent_must_be_same_type(self, geo_type):
        other = GeographyType.objects.create(name='Other', code='other', levels=['region'])
        other_region = GeographyNode.objects.create(
            geography_type=other, name='O', code='O', level='region',
        )
        with pytest.raises(BusinessError, match='different geography type'):
            GeographyNodeService.create({
                'geography_type': geo_type, 'name': 'S', 'code': 'S',
                'level': 'state', 'parent': other_region,
            })

    def test_valid_chain_creates_path(self, geo_type):
        region = GeographyNodeService.create({
            'geography_type': geo_type, 'name': 'North', 'code': 'N',
            'level': 'region', 'parent': None,
        })
        state = GeographyNodeService.create({
            'geography_type': geo_type, 'name': 'Delhi', 'code': 'DL',
            'level': 'state', 'parent': region,
        })
        assert state.path == '/N/DL/'
        assert state.depth == 1


# ── Geography move ──────────────────────────────────────────────────────────────

@pytest.fixture
def geo_tree(geo_type):
    """N(region) > DL(state) > NEW(district) > T1(town); plus UP(state) under N."""
    n = GeographyNode.objects.create(geography_type=geo_type, name='North', code='N', level='region')
    dl = GeographyNode.objects.create(geography_type=geo_type, name='Delhi', code='DL', level='state', parent=n)
    new = GeographyNode.objects.create(geography_type=geo_type, name='New Delhi', code='NEW', level='district', parent=dl)
    t1 = GeographyNode.objects.create(geography_type=geo_type, name='CP', code='T1', level='town', parent=new)
    up = GeographyNode.objects.create(geography_type=geo_type, name='UP', code='UP', level='state', parent=n)
    return {'N': n, 'DL': dl, 'NEW': new, 'T1': t1, 'UP': up}


@pytest.mark.django_db
class TestGeoMove:
    def test_move_recomputes_all_descendant_paths(self, geo_tree):
        # Move the 'NEW' district from Delhi to UP — its town child must follow.
        GeographyNodeService.move(geo_tree['NEW'].id, geo_tree['UP'].id)

        new = GeographyNode.objects.get(pk=geo_tree['NEW'].pk)
        t1 = GeographyNode.objects.get(pk=geo_tree['T1'].pk)
        assert new.path == '/N/UP/NEW/'
        assert new.depth == 2
        assert t1.path == '/N/UP/NEW/T1/'
        assert t1.depth == 3

    def test_move_audited(self, geo_tree):
        GeographyNodeService.move(geo_tree['NEW'].id, geo_tree['UP'].id)
        log = AuditLog.objects.filter(action='move', entity_type='geography_node').first()
        assert log is not None
        assert log.changes['descendants_moved'] == 1

    def test_move_rejects_cycle(self, geo_tree):
        # Cannot move 'DL' under its own descendant 'NEW'.
        with pytest.raises(BusinessError, match='circular'):
            GeographyNodeService.move(geo_tree['DL'].id, geo_tree['NEW'].id)

    def test_move_to_root(self, geo_tree):
        GeographyNodeService.move(geo_tree['DL'].id, None)
        dl = GeographyNode.objects.get(pk=geo_tree['DL'].pk)
        assert dl.path == '/DL/'
        assert dl.depth == 0
        # descendant town follows
        t1 = GeographyNode.objects.get(pk=geo_tree['T1'].pk)
        assert t1.path == '/DL/NEW/T1/'


# ── Geography deactivate guards ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestGeoDeactivateGuards:
    def test_type_deactivate_blocked_with_nodes(self, geo_tree, geo_type):
        with pytest.raises(BusinessError, match='active'):
            GeographyTypeService.deactivate(geo_type)

    def test_node_deactivate_blocked_with_children(self, geo_tree):
        with pytest.raises(BusinessError, match='child node'):
            GeographyNodeService.deactivate(geo_tree['DL'])

    def test_node_deactivate_blocked_with_open_assignment(self, geo_tree, outlet_type):
        from apps.assignments.services import AssignmentService

        shop = Node.objects.create(
            entity_type=outlet_type, name='Shop', code='shop1',
            effective_from=date.today(),
        )
        AssignmentService.create(
            assignee_id=shop.pk, scope_id=geo_tree['T1'].pk,
            effective_from=date.today(),
        )
        with pytest.raises(BusinessError, match='open assignment'):
            GeographyNodeService.deactivate(geo_tree['T1'])

    def test_leaf_node_deactivate_succeeds(self, geo_tree):
        GeographyNodeService.deactivate(geo_tree['T1'])
        geo_tree['T1'].refresh_from_db()
        assert geo_tree['T1'].is_active is False


# ── Nested serializer output ────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNestedSerializers:
    def test_entity_detail_emits_nested_channel_and_owned_scopes(
        self, channel, geo_type, outlet_type, geo_tree,
    ):
        from apps.assignments.services import AssignmentService
        from apps.hierarchy.serializers import NodeDetailSerializer

        entity = Node.objects.create(
            entity_type=outlet_type, name='Shop', code='shop1',
            channel=channel, effective_from=date.today(),
        )
        AssignmentService.create(
            assignee_id=entity.pk, scope_id=geo_tree['T1'].pk,
            effective_from=date.today(),
        )
        data = NodeDetailSerializer(entity).data
        assert data['channel'] == {'id': channel.id, 'code': 'GT', 'name': 'General Trade'}
        assert data['owned_scopes'] == [{
            'id': geo_tree['T1'].id, 'name': geo_tree['T1'].name, 'code': 'T1',
            'level': 'town', 'since': str(date.today()),
        }]

    def test_display_code_tracks_ownership(self, outlet_type, geo_tree):
        """display_code = {TYPE}-{primary owned territory}; recomputed live from
        assignments so it follows a transfer without the immutable `code` moving."""
        from apps.assignments.services import AssignmentService
        from apps.hierarchy.serializers import NodeDetailSerializer

        entity = Node.objects.create(
            entity_type=outlet_type, name='Shop', code='OUTLET-0001',
            effective_from=date.today(),
        )
        AssignmentService.create(
            assignee_id=entity.pk, scope_id=geo_tree['DL'].pk,
            effective_from=date.today() - timedelta(days=10),
        )
        assert NodeDetailSerializer(entity).data['display_code'] == 'OUTLET-DL'

        # Hand the territory over and own another → display_code follows, code stays put.
        other = Node.objects.create(
            entity_type=outlet_type, name='Shop2', code='OUTLET-0002',
            effective_from=date.today(),
        )
        AssignmentService.transfer(
            scope_id=geo_tree['DL'].pk, new_assignee_id=other.pk,
            effective_from=date.today(),
        )
        AssignmentService.create(
            assignee_id=entity.pk, scope_id=geo_tree['UP'].pk,
            effective_from=date.today(),
        )
        del entity._owned_assignments  # drop the serializer cache
        data = NodeDetailSerializer(entity).data
        assert data['display_code'] == 'OUTLET-UP'
        assert data['code'] == 'OUTLET-0001'

    def test_display_code_falls_back_to_type_without_geography(self, outlet_type):
        from apps.hierarchy.serializers import NodeDetailSerializer

        entity = Node.objects.create(
            entity_type=outlet_type, name='Shop', code='OUTLET-0001',
            effective_from=date.today(),
        )
        assert NodeDetailSerializer(entity).data['display_code'] == 'OUTLET'
