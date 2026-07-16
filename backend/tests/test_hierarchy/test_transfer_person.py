"""
Unified person transfer (TransferService.transfer_person).

One atomic operation across both trees: direct reports are promoted to the
departing entity's parent (or reassign_reports_to), the person lands in a new
seat or an existing vacant seat, and their owned territories are settled per
territory_handover (successor / release / keep). Ownership flips are proven
through AssignmentService.owner_of as-of dates — never a static FK.
"""
from datetime import date, timedelta

import pytest
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User
from apps.assignments.services import AssignmentService
from apps.audit.models import AuditLog
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import Node, NodeType, GeographyNode, GeographyType
from apps.hierarchy.services import NodeService, TransferService

ENTITIES = '/api/v1/entities'
TODAY = date.today()
LAST_MONTH = TODAY - timedelta(days=30)
YESTERDAY = TODAY - timedelta(days=1)


def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email='root@example.com', password='pass')


@pytest.fixture
def types(db):
    """NSM > RSM > ASM > SO. RSM may temporarily hold SOs so a team can be promoted
    to the grandparent (an RSM) when its ASM is transferred out."""
    role = Role.objects.create(code='mgr_role', name='Mgr', permissions={})
    nsm = NodeType.objects.create(
        name='NSM', code='NSM', level_order=1, effective_from=TODAY,
        is_root_type=True, allowed_child_types=['RSM'], is_loginable=True,
        default_role=role, display_config={'login_method': 'otp_only'},
    )
    rsm = NodeType.objects.create(
        name='RSM', code='RSM', level_order=2, effective_from=TODAY,
        allowed_parent_types=['NSM'], allowed_child_types=['ASM', 'SO'],
        is_loginable=True, default_role=role, display_config={'login_method': 'otp_only'},
    )
    asm = NodeType.objects.create(
        name='ASM', code='ASM', level_order=3, effective_from=TODAY,
        allowed_parent_types=['RSM'], allowed_child_types=['SO'],
        is_loginable=True, default_role=role, display_config={'login_method': 'otp_only'},
    )
    so = NodeType.objects.create(
        name='SO', code='SO', level_order=4, effective_from=TODAY,
        allowed_parent_types=['ASM', 'RSM'], is_leaf=True,
    )
    return {'NSM': nsm, 'RSM': rsm, 'ASM': asm, 'SO': so}


@pytest.fixture
def geo(db):
    gt = GeographyType.objects.create(
        name='Sales Geo', code='sales_geo', levels=['region', 'city'],
    )
    north = GeographyNode.objects.create(geography_type=gt, name='North', code='NORTH', level='region')
    delhi = GeographyNode.objects.create(geography_type=gt, name='Delhi', code='DELHI', level='city', parent=north)
    ggn = GeographyNode.objects.create(geography_type=gt, name='Gurgaon', code='GGN', level='city', parent=north)
    south = GeographyNode.objects.create(geography_type=gt, name='South', code='SOUTH', level='region')
    blr = GeographyNode.objects.create(geography_type=gt, name='Bangalore', code='BLR', level='city', parent=south)
    return {'north': north, 'delhi': delhi, 'ggn': ggn, 'south': south, 'blr': blr}


def _mk(t, code, parent=None, status='active'):
    return Node.objects.create(
        entity_type=t, name=code, code=code, parent=parent,
        status=status, effective_from=TODAY,
    )


def _own(entity, scope, since=LAST_MONTH):
    return AssignmentService.create(
        assignee_id=entity.pk, scope_id=scope.pk, effective_from=since,
    )


@pytest.fixture
def org(types, geo, admin_user):
    """NSM → {RSM North, RSM South}; under RSM North a Delhi ASM (with incumbent,
    owning DELHI) + an SO report (owning GGN), plus a backfill ASM owning nothing."""
    nsm = _mk(types['NSM'], 'NSM1')
    rsm_north = _mk(types['RSM'], 'RSM_N', parent=nsm)
    rsm_south = _mk(types['RSM'], 'RSM_S', parent=nsm)
    asm_delhi = NodeService.create_entity(
        {'entity_type_id': types['ASM'].id, 'name': 'Priya', 'code': 'ASM_DL',
         'parent_id': rsm_north.id, 'mobile': '9000000001'},
        admin_user,
    )
    asm_backfill = _mk(types['ASM'], 'ASM_DL_BK', parent=rsm_north)
    so = _mk(types['SO'], 'SO_DL', parent=asm_delhi)
    _own(rsm_north, geo['north'])
    _own(rsm_south, geo['south'])
    _own(asm_delhi, geo['delhi'])
    _own(so, geo['ggn'])
    return {
        'nsm': nsm, 'rsm_north': rsm_north, 'rsm_south': rsm_south,
        'asm_delhi': asm_delhi, 'asm_backfill': asm_backfill, 'so': so,
    }


@pytest.mark.django_db
class TestTransferNewSeat:

    def test_keep_team_promoted_person_moves_territories_stay(self, org, geo, admin_user):
        TransferService.transfer_person(
            org['asm_delhi'].id, mode='new_seat', new_parent_id=org['rsm_south'].id,
            territory_handover='keep',
            reason='Posted to South', effective_date=TODAY, user=admin_user,
        )
        so = Node.objects.get(pk=org['so'].id)
        asm = Node.objects.get(pk=org['asm_delhi'].id)
        # Team stayed, now reports to the grandparent (RSM North), keeps its territory.
        assert so.parent_id == org['rsm_north'].id
        assert so.path == '/NSM1/RSM_N/SO_DL/'
        assert AssignmentService.owner_of(geo['ggn']) == so
        # The person moved under RSM South; same node id → still owns Delhi.
        assert asm.parent_id == org['rsm_south'].id
        assert not asm.get_direct_children().exists()
        assert AssignmentService.owner_of(geo['delhi']) == asm

    def test_successor_flips_ownership_on_effective_date(self, org, geo, admin_user):
        TransferService.transfer_person(
            org['asm_delhi'].id, mode='new_seat', new_parent_id=org['rsm_south'].id,
            territory_handover='successor', successor_id=org['asm_backfill'].id,
            reason='Backfill takes Delhi', effective_date=TODAY, user=admin_user,
        )
        assert AssignmentService.owner_of(geo['delhi'], on=TODAY) == org['asm_backfill']
        # As-of yesterday the outgoing ASM still owned it — history intact.
        assert AssignmentService.owner_of(geo['delhi'], on=YESTERDAY) == org['asm_delhi']

    def test_release_leaves_territory_unowned(self, org, geo, admin_user):
        TransferService.transfer_person(
            org['asm_delhi'].id, mode='new_seat', new_parent_id=org['rsm_south'].id,
            territory_handover='release',
            reason='No replacement yet', effective_date=TODAY, user=admin_user,
        )
        assert AssignmentService.owner_of(geo['delhi'], on=TODAY) is None
        assert AssignmentService.owner_of(geo['delhi'], on=YESTERDAY) == org['asm_delhi']

    def test_reassign_reports_to_specific_manager(self, org, geo, admin_user):
        TransferService.transfer_person(
            org['asm_delhi'].id, mode='new_seat', new_parent_id=org['rsm_south'].id,
            reassign_reports_to=org['asm_backfill'].id,
            reason='x', effective_date=TODAY, user=admin_user,
        )
        so = Node.objects.get(pk=org['so'].id)
        assert so.parent_id == org['asm_backfill'].id
        assert AssignmentService.owner_of(geo['ggn']) == org['so']

    def test_incumbent_user_travels_with_node(self, org, admin_user):
        incumbent = Node.objects.get(pk=org['asm_delhi'].id).user
        TransferService.transfer_person(
            org['asm_delhi'].id, mode='new_seat', new_parent_id=org['rsm_south'].id,
            reason='x', effective_date=TODAY, user=admin_user,
        )
        incumbent.refresh_from_db()
        assert incumbent.entity_id == org['asm_delhi'].id

    def test_single_audit_entry_with_territory_moves(self, org, geo, admin_user):
        TransferService.transfer_person(
            org['asm_delhi'].id, mode='new_seat', new_parent_id=org['rsm_south'].id,
            territory_handover='successor', successor_id=org['asm_backfill'].id,
            reason='Posted South', effective_date=TODAY, user=admin_user,
        )
        log = AuditLog.objects.get(
            action='transfer', entity_type='hierarchy.Node', entity_id=org['asm_delhi'].id,
        )
        assert log.changes['mode'] == 'new_seat'
        assert log.changes['territory_handover'] == 'successor'
        assert log.changes['territory_moves'] == [{
            'scope_id': geo['delhi'].id, 'scope_code': 'DELHI',
            'action': 'successor', 'to': org['asm_backfill'].id,
        }]
        assert org['so'].id in log.changes['reports_promoted']


@pytest.mark.django_db
class TestTransferOccupyVacant:

    def _vacant_seat(self, org, types, admin_user, code='ASM_S_VAC'):
        return NodeService.create_entity(
            {'entity_type_id': types['ASM'].id, 'name': 'South ASM Seat',
             'code': code, 'parent_id': org['rsm_south'].id, 'status': 'vacant'},
            admin_user,
        )

    def test_relink_source_deactivated_keep_moves_territories(self, org, types, geo, admin_user):
        vacant = self._vacant_seat(org, types, admin_user)
        incumbent = Node.objects.get(pk=org['asm_delhi'].id).user

        TransferService.transfer_person(
            org['asm_delhi'].id, mode='occupy_vacant', target_entity_id=vacant.id,
            territory_handover='keep',
            reason='Fill South vacancy', effective_date=TODAY, user=admin_user,
        )

        incumbent.refresh_from_db()
        vacant.refresh_from_db()
        source = Node.objects.get(pk=org['asm_delhi'].id)
        assert incumbent.entity_id == vacant.id      # person now in the South seat
        assert vacant.status == 'active'
        assert source.status == 'inactive'           # vacated Delhi seat retired
        # 'keep' on a seat change → the territory follows the person to the new seat.
        assert AssignmentService.owner_of(geo['delhi'], on=TODAY) == vacant
        assert AssignmentService.owner_of(geo['delhi'], on=YESTERDAY) == source

    def test_seat_territories_come_with_the_seat(self, org, types, geo, admin_user):
        # The vacant seat already owns BLR — whoever occupies it inherits automatically.
        vacant = self._vacant_seat(org, types, admin_user)
        _own(vacant, geo['blr'])

        TransferService.transfer_person(
            org['asm_delhi'].id, mode='occupy_vacant', target_entity_id=vacant.id,
            territory_handover='release',
            reason='South posting', effective_date=TODAY, user=admin_user,
        )
        assert AssignmentService.owner_of(geo['blr']) == vacant
        assert AssignmentService.owner_of(geo['delhi'], on=TODAY) is None

    def test_vacant_seat_created_without_user(self, org, types, admin_user):
        vacant = NodeService.create_entity(
            {'entity_type_id': types['ASM'].id, 'name': 'Seat', 'code': 'SEAT1',
             'parent_id': org['rsm_south'].id, 'status': 'vacant',
             'mobile': '9111111111'},
            admin_user,
        )
        with pytest.raises(ObjectDoesNotExist):
            _ = vacant.user

    def test_target_must_be_vacant(self, org, types, admin_user):
        active_seat = _mk(types['ASM'], 'ASM_S_ACT', parent=org['rsm_south'])
        with pytest.raises(BusinessError, match='not vacant'):
            TransferService.transfer_person(
                org['asm_delhi'].id, mode='occupy_vacant', target_entity_id=active_seat.id,
                reason='x', effective_date=TODAY, user=admin_user,
            )

    def test_target_type_must_match(self, org, types, admin_user):
        vacant_rsm = NodeService.create_entity(
            {'entity_type_id': types['RSM'].id, 'name': 'RSM Seat', 'code': 'RSM_VAC',
             'parent_id': org['nsm'].id, 'status': 'vacant'},
            admin_user,
        )
        with pytest.raises(BusinessError, match='different entity type'):
            TransferService.transfer_person(
                org['asm_delhi'].id, mode='occupy_vacant', target_entity_id=vacant_rsm.id,
                reason='x', effective_date=TODAY, user=admin_user,
            )


@pytest.mark.django_db
class TestTransferEdges:

    def test_successor_required_for_successor_handover(self, org, admin_user):
        with pytest.raises(BusinessError, match='successor_id'):
            TransferService.transfer_person(
                org['asm_delhi'].id, mode='new_seat', new_parent_id=org['rsm_south'].id,
                territory_handover='successor',
                reason='x', effective_date=TODAY, user=admin_user,
            )

    def test_successor_cannot_be_self(self, org, admin_user):
        with pytest.raises(BusinessError, match='Successor cannot be'):
            TransferService.transfer_person(
                org['asm_delhi'].id, mode='new_seat', new_parent_id=org['rsm_south'].id,
                territory_handover='successor', successor_id=org['asm_delhi'].id,
                reason='x', effective_date=TODAY, user=admin_user,
            )

    def test_root_with_children_needs_reassign_target(self, org, admin_user):
        # NSM is a root (no parent) but has RSM children → nowhere to promote them.
        with pytest.raises(BusinessError, match='no parent to promote'):
            TransferService.transfer_person(
                org['nsm'].id, mode='new_seat', new_parent_id=org['rsm_south'].id,
                reason='x', effective_date=TODAY, user=admin_user,
            )

    def test_promote_to_grandparent_rejected_when_type_invalid(self, types, admin_user):
        # Strict blueprint: SO only under ASM, so it cannot be promoted to an RSM grandparent.
        strict_so = NodeType.objects.create(
            name='SOX', code='SOX', level_order=5, effective_from=TODAY,
            allowed_parent_types=['ASM'], is_leaf=True,
        )
        nsm = _mk(types['NSM'], 'N1')
        rsm = _mk(types['RSM'], 'R1', parent=nsm)
        asm = _mk(types['ASM'], 'A1', parent=rsm)
        _mk(strict_so, 'S1', parent=asm)
        with pytest.raises(BusinessError, match='Cannot promote report'):
            TransferService.transfer_person(
                asm.id, mode='new_seat', new_parent_id=nsm.id,
                reason='x', effective_date=TODAY, user=admin_user,
            )


@pytest.mark.django_db
class TestTransferAPI:

    def test_api_successor_handover_requires_successor_id(self, org, admin_user):
        resp = _auth_client(admin_user).post(
            f'{ENTITIES}/{org["asm_delhi"].id}/transfer/',
            {'mode': 'new_seat', 'new_parent_id': org['rsm_south'].id,
             'territory_handover': 'successor',
             'reason': 'x', 'effective_date': str(TODAY)},
            format='json',
        )
        assert resp.status_code == 400  # serializer validation

    def test_api_transfer_with_successor(self, org, geo, admin_user):
        resp = _auth_client(admin_user).post(
            f'{ENTITIES}/{org["asm_delhi"].id}/transfer/',
            {'mode': 'new_seat', 'new_parent_id': org['rsm_south'].id,
             'territory_handover': 'successor', 'successor_id': org['asm_backfill'].id,
             'reason': 'Posted South', 'effective_date': str(TODAY)},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['parent_info']['code'] == 'RSM_S'
        assert resp.data['owned_scopes'] == []   # handed everything to the successor
        assert AssignmentService.owner_of(geo['delhi']) == org['asm_backfill']

    def test_api_transfer_impact(self, org, geo, admin_user):
        resp = _auth_client(admin_user).get(
            f'{ENTITIES}/{org["asm_delhi"].id}/transfer-impact/',
        )
        assert resp.status_code == 200
        assert resp.data['entity']['code'] == 'ASM_DL'
        assert resp.data['current_parent']['code'] == 'RSM_N'
        assert [t['code'] for t in resp.data['owned_territories']] == ['DELHI']
        assert [r['code'] for r in resp.data['direct_reports']] == ['SO_DL']
