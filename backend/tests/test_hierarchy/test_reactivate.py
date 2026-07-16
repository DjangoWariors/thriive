"""
Reactivation — the reverse of soft-delete for entities and users.

Node reactivate flips status back to active, re-enables the linked user, and
is blocked under an inactive parent. User reactivate flips is_active back on.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.audit.models import AuditLog
from apps.hierarchy.models import Node, NodeType
from apps.hierarchy.services import NodeService

ENTITIES = '/api/v1/entities'
USERS = '/api/v1/auth/users'


def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email='root@example.com', password='pass')


@pytest.fixture
def user_mgr(db):
    user = User.objects.create_user(email='umgr@example.com', password='pass')
    role = Role.objects.create(code='user_mgr', name='User Manager',
                               permissions={'user_management': 'full'})
    UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


@pytest.fixture
def loginable_type(db):
    return NodeType.objects.create(
        name='Retailer', code='RET', level_order=2, is_loginable=True,
        attribute_schema=[{'key': 'mobile', 'label': 'Mobile', 'type': 'phone', 'required': True}],
        display_config={'login_method': 'otp_only'}, effective_from=date.today(),
    )


@pytest.fixture
def node_type(db):
    return NodeType.objects.create(name='Node', code='NODE', level_order=1, effective_from=date.today())


# ── Node reactivation (service) ─────────────────────────────────────────────

@pytest.mark.django_db
class TestNodeReactivateService:

    def test_reactivate_restores_status_and_user(self, admin_user, loginable_type):
        entity = NodeService.create_entity(
            {'entity_type_id': loginable_type.id, 'name': 'Shop A', 'code': 'A',
             'attributes': {'mobile': '9876543210'}},
            admin_user,
        )
        NodeService.deactivate_entity(entity.id, reason='closed', user=admin_user)
        entity.refresh_from_db()
        assert entity.status == 'inactive'
        assert entity.user.is_active is False

        NodeService.reactivate_entity(entity.id, reason='reopened', user=admin_user)
        entity.refresh_from_db()
        assert entity.status == 'active'
        assert entity.user.is_active is True
        assert AuditLog.objects.filter(action='reactivate', entity_id=entity.id).exists()

    def test_reactivate_blocked_under_inactive_parent(self, admin_user, node_type):
        parent = Node.objects.create(entity_type=node_type, name='P', code='P', effective_from=date.today())
        child = Node.objects.create(entity_type=node_type, name='C', code='C', parent=parent, effective_from=date.today())
        # Cascade deactivation sets both parent and child to inactive.
        NodeService.bulk_deactivate([parent.id], reason='x', user=admin_user, cascade=True)

        from apps.core.exceptions import BusinessError
        with pytest.raises(BusinessError):
            NodeService.reactivate_entity(child.id, reason='y', user=admin_user)

    def test_reactivate_already_active_rejected(self, admin_user, node_type):
        e = Node.objects.create(entity_type=node_type, name='E', code='E', effective_from=date.today())
        from apps.core.exceptions import BusinessError
        with pytest.raises(BusinessError):
            NodeService.reactivate_entity(e.id, reason='y', user=admin_user)


# ── Node reactivation (API) ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestNodeReactivateAPI:

    def test_reactivate_endpoint(self, admin_user, node_type):
        e = Node.objects.create(entity_type=node_type, name='E', code='E', effective_from=date.today())
        NodeService.deactivate_entity(e.id, reason='x', user=admin_user)
        resp = _auth_client(admin_user).post(f'{ENTITIES}/{e.id}/reactivate/', {'reason': 'back'}, format='json')
        assert resp.status_code == 200
        assert resp.data['status'] == 'active'

    def test_reactivate_inactive_parent_returns_422(self, admin_user, node_type):
        parent = Node.objects.create(entity_type=node_type, name='P', code='P', effective_from=date.today())
        child = Node.objects.create(entity_type=node_type, name='C', code='C', parent=parent, effective_from=date.today())
        NodeService.bulk_deactivate([parent.id], reason='x', user=admin_user, cascade=True)
        resp = _auth_client(admin_user).post(f'{ENTITIES}/{child.id}/reactivate/', {}, format='json')
        assert resp.status_code == 422


# ── Bulk reactivation ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBulkReactivate:

    def test_bulk_reactivate_parent_and_child(self, admin_user, node_type):
        parent = Node.objects.create(entity_type=node_type, name='P', code='P', effective_from=date.today())
        child = Node.objects.create(entity_type=node_type, name='C', code='C', parent=parent, effective_from=date.today())
        NodeService.bulk_deactivate([parent.id], reason='x', user=admin_user, cascade=True)

        resp = _auth_client(admin_user).post(
            f'{ENTITIES}/bulk-reactivate/',
            {'entity_ids': [child.id, parent.id], 'reason': 'reopen'},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['reactivated'] == 2
        parent.refresh_from_db(); child.refresh_from_db()
        assert parent.status == 'active' and child.status == 'active'

    def test_bulk_reactivate_child_only_blocked(self, admin_user, node_type):
        parent = Node.objects.create(entity_type=node_type, name='P', code='P', effective_from=date.today())
        child = Node.objects.create(entity_type=node_type, name='C', code='C', parent=parent, effective_from=date.today())
        NodeService.bulk_deactivate([parent.id], reason='x', user=admin_user, cascade=True)

        resp = _auth_client(admin_user).post(
            f'{ENTITIES}/bulk-reactivate/',
            {'entity_ids': [child.id]},
            format='json',
        )
        assert resp.status_code == 422
        child.refresh_from_db()
        assert child.status == 'inactive'


# ── User reactivation (API) ───────────────────────────────────────────────────

@pytest.mark.django_db
class TestUserReactivateAPI:

    def test_reactivate_user(self, user_mgr):
        target = User.objects.create_user(email='gone@example.com', is_active=False)
        resp = _auth_client(user_mgr).post(f'{USERS}/{target.id}/reactivate/', {}, format='json')
        assert resp.status_code == 200
        target.refresh_from_db()
        assert target.is_active is True
        assert AuditLog.objects.filter(action='reactivate', entity_type='user', entity_id=target.id).exists()

    def test_reactivate_missing_user_404(self, user_mgr):
        resp = _auth_client(user_mgr).post(f'{USERS}/999999/reactivate/', {}, format='json')
        assert resp.status_code == 404
