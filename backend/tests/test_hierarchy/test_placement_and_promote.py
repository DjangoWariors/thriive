"""
Node-hierarchy integrity: bidirectional placement rules (allowed_parent_types
+ allowed_child_types + leaf + root) and the change-type / promotion flow.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.audit.models import AuditLog
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import Node, NodeType
from apps.hierarchy.services import NodeService

ENTITIES = '/api/v1/entities'


def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email='root@example.com', password='pass')


# A realistic 3-level sales blueprint: NSM > RSM > ASM (+ SO leaf).
@pytest.fixture
def types(db):
    nsm_role = Role.objects.create(code='nsm_role', name='NSM', permissions={})
    rsm_role = Role.objects.create(code='rsm_role', name='RSM', permissions={})
    nsm = NodeType.objects.create(
        name='NSM', code='NSM', level_order=1, effective_from=date.today(),
        is_root_type=True, allowed_child_types=['RSM'], is_loginable=True, default_role=nsm_role,
        display_config={'login_method': 'otp_only'},
    )
    rsm = NodeType.objects.create(
        name='RSM', code='RSM', level_order=2, effective_from=date.today(),
        allowed_parent_types=['NSM'], allowed_child_types=['ASM'],
        is_loginable=True, default_role=rsm_role, display_config={'login_method': 'otp_only'},
    )
    asm = NodeType.objects.create(
        name='ASM', code='ASM', level_order=3, effective_from=date.today(),
        allowed_parent_types=['RSM'], allowed_child_types=['SO'],
        is_loginable=True, default_role=rsm_role, display_config={'login_method': 'otp_only'},
    )
    so = NodeType.objects.create(
        name='SO', code='SO', level_order=4, effective_from=date.today(),
        allowed_parent_types=['ASM'], is_leaf=True,
    )
    return {'NSM': nsm, 'RSM': rsm, 'ASM': asm, 'SO': so}


def _mk(t, code, parent=None, attrs=None):
    return Node.objects.create(
        entity_type=t, name=code, code=code, parent=parent,
        attributes=attrs or {}, effective_from=date.today(),
    )


# ── Placement rules ───────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPlacement:

    def test_nsm_cannot_be_moved_under_rsm(self, admin_user, types):
        nsm = _mk(types['NSM'], 'NSM1')
        rsm = _mk(types['RSM'], 'RSM1', parent=nsm)
        # NSM under RSM: blocked by root rule + RSM.allowed_child_types (no NSM).
        resp = _auth_client(admin_user).post(
            f'{ENTITIES}/{nsm.id}/move/',
            {'new_parent_id': rsm.id, 'reason': 'x', 'effective_date': '2026-06-03'},
            format='json',
        )
        assert resp.status_code == 422

    def test_parent_allowed_child_types_enforced(self, admin_user, types):
        # SO directly under RSM: RSM.allowed_child_types=['ASM'] → rejected.
        nsm = _mk(types['NSM'], 'NSM1')
        rsm = _mk(types['RSM'], 'RSM1', parent=nsm)
        errs = NodeService._validate_placement(types['SO'], rsm)
        assert errs  # not allowed

    def test_leaf_cannot_have_children(self, admin_user, types):
        nsm = _mk(types['NSM'], 'NSM1')
        rsm = _mk(types['RSM'], 'RSM1', parent=nsm)
        asm = _mk(types['ASM'], 'ASM1', parent=rsm)
        so = _mk(types['SO'], 'SO1', parent=asm)
        errs = NodeService._validate_placement(types['SO'], so)
        assert any('leaf' in e for e in errs)

    def test_root_type_rejected_under_parent(self, types):
        nsm = _mk(types['NSM'], 'NSM1')
        rsm = _mk(types['RSM'], 'RSM1', parent=nsm)
        errs = NodeService._validate_placement(types['NSM'], rsm)
        assert any('root type' in e for e in errs)

    def test_valid_placement_passes(self, types):
        nsm = _mk(types['NSM'], 'NSM1')
        assert NodeService._validate_placement(types['RSM'], nsm) == []


# ── Change type / promotion ───────────────────────────────────────────────────

@pytest.mark.django_db
class TestChangeType:

    def test_promote_asm_to_rsm(self, admin_user, types):
        nsm = _mk(types['NSM'], 'NSM1')
        rsm = _mk(types['RSM'], 'RSM1', parent=nsm)
        asm = _mk(types['ASM'], 'ASM1', parent=rsm)

        result = NodeService.change_entity_type(
            entity_id=asm.id, new_type_id=types['RSM'].id, new_parent_id=nsm.id,
            attributes=None, reason='promotion', effective_date=date.today(), user=admin_user,
        )
        asm.refresh_from_db()
        assert asm.entity_type_id == types['RSM'].id
        assert asm.parent_id == nsm.id
        assert asm.path == '/NSM1/ASM1/'
        assert AuditLog.objects.filter(action='promote', entity_id=asm.id).exists()

    def test_promote_blocked_when_reports_invalid(self, admin_user, types):
        # ASM with an SO report; promote ASM→RSM — SO can't sit under RSM.
        nsm = _mk(types['NSM'], 'NSM1')
        rsm = _mk(types['RSM'], 'RSM1', parent=nsm)
        asm = _mk(types['ASM'], 'ASM1', parent=rsm)
        _mk(types['SO'], 'SO1', parent=asm)

        with pytest.raises(BusinessError):
            NodeService.change_entity_type(
                entity_id=asm.id, new_type_id=types['RSM'].id, new_parent_id=nsm.id,
                attributes=None, reason='x', effective_date=date.today(), user=admin_user,
            )

    def test_promote_with_report_reassignment(self, admin_user, types):
        nsm = _mk(types['NSM'], 'NSM1')
        rsm = _mk(types['RSM'], 'RSM1', parent=nsm)
        asm1 = _mk(types['ASM'], 'ASM1', parent=rsm)
        asm2 = _mk(types['ASM'], 'ASM2', parent=rsm)  # the backfill
        so = _mk(types['SO'], 'SO1', parent=asm1)

        NodeService.change_entity_type(
            entity_id=asm1.id, new_type_id=types['RSM'].id, new_parent_id=nsm.id,
            attributes=None, reason='promotion', effective_date=date.today(), user=admin_user,
            reassign_reports_to=asm2.id,
        )
        so.refresh_from_db(); asm1.refresh_from_db()
        assert so.parent_id == asm2.id           # report moved to backfill ASM
        assert asm1.entity_type_id == types['RSM'].id

    def test_change_type_swaps_linked_user_role(self, admin_user, types):
        # Build an ASM with a linked user via the service (auto-creates user + ASM role).
        nsm = _mk(types['NSM'], 'NSM1')
        rsm = _mk(types['RSM'], 'RSM1', parent=nsm)
        asm = NodeService.create_entity(
            {'entity_type_id': types['ASM'].id, 'name': 'Ramesh', 'code': 'ASM1',
             'parent_id': rsm.id, 'attributes': {}, 'mobile': '9000000001'},
            admin_user,
        )
        NodeService.change_entity_type(
            entity_id=asm.id, new_type_id=types['RSM'].id, new_parent_id=nsm.id,
            attributes=None, reason='promotion', effective_date=date.today(), user=admin_user,
        )
        linked = Node.objects.get(pk=asm.id).user
        active_role_codes = set(
            linked.user_roles.filter(is_active=True).values_list('role__code', flat=True)
        )
        assert 'rsm_role' in active_role_codes

    def test_change_type_api(self, admin_user, types):
        nsm = _mk(types['NSM'], 'NSM1')
        rsm = _mk(types['RSM'], 'RSM1', parent=nsm)
        asm = _mk(types['ASM'], 'ASM1', parent=rsm)
        resp = _auth_client(admin_user).post(
            f'{ENTITIES}/{asm.id}/change-type/',
            {'new_type_id': types['RSM'].id, 'new_parent_id': nsm.id, 'reason': 'promo'},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['entity_type']['code'] == 'RSM'
