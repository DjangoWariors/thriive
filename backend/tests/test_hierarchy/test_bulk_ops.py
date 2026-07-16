"""
Phase B4 — bulk transfer / deactivate / role assignment.

Node bulk-move (path recompute + all-or-nothing), entity bulk-deactivate
(block vs cascade), and user bulk-roles (add vs replace).
"""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.hierarchy.models import Node, NodeType

ENTITIES = '/api/v1/entities'
USERS = '/api/v1/auth/users'


def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


@pytest.fixture
def hierarchy_user(db):
    user = User.objects.create_user(email='hmgr@example.com', password='pass')
    role = Role.objects.create(code='hier_mgr', name='Hierarchy Manager',
                               permissions={'hierarchy_management': 'full'})
    UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


@pytest.fixture
def user_mgr(db):
    user = User.objects.create_user(email='umgr@example.com', password='pass')
    role = Role.objects.create(code='user_mgr', name='User Manager',
                               permissions={'user_management': 'full'})
    UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


@pytest.fixture
def node_type(db):
    return NodeType.objects.create(name='Node', code='NODE', level_order=1, effective_from=date.today())


def _mk(node_type, code, parent=None):
    return Node.objects.create(
        entity_type=node_type, name=code, code=code, parent=parent, effective_from=date.today(),
    )


# ── Bulk move ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBulkMove:

    def test_moves_many_and_recomputes_paths(self, hierarchy_user, node_type):
        root_a = _mk(node_type, 'A')
        root_b = _mk(node_type, 'B')
        c = _mk(node_type, 'C', parent=root_a)
        d = _mk(node_type, 'D', parent=root_a)
        grandchild = _mk(node_type, 'GC', parent=c)

        resp = _auth_client(hierarchy_user).post(
            f'{ENTITIES}/bulk-move/',
            {'entity_ids': [c.id, d.id], 'new_parent_id': root_b.id,
             'reason': 'reorg', 'effective_date': '2026-06-02'},
            format='json',
        )
        assert resp.status_code == 200, resp.data
        assert resp.data['moved'] == 2

        c.refresh_from_db(); d.refresh_from_db(); grandchild.refresh_from_db()
        assert c.path == '/B/C/'
        assert d.path == '/B/D/'
        # Descendant carried along.
        assert grandchild.path == '/B/C/GC/'

    def test_all_or_nothing_on_circular(self, hierarchy_user, node_type):
        root_a = _mk(node_type, 'A')
        child = _mk(node_type, 'CH', parent=root_a)
        # Moving A under its own child CH is circular → whole batch rejected.
        resp = _auth_client(hierarchy_user).post(
            f'{ENTITIES}/bulk-move/',
            {'entity_ids': [root_a.id], 'new_parent_id': child.id,
             'reason': 'x', 'effective_date': '2026-06-02'},
            format='json',
        )
        assert resp.status_code == 422
        assert resp.data['errors'][0]['id'] == root_a.id
        root_a.refresh_from_db()
        assert root_a.path == '/A/'  # unchanged


# ── Bulk deactivate ───────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBulkDeactivate:

    def test_blocks_entity_with_unselected_children(self, hierarchy_user, node_type):
        parent = _mk(node_type, 'P')
        _mk(node_type, 'CH', parent=parent)
        resp = _auth_client(hierarchy_user).post(
            f'{ENTITIES}/bulk-deactivate/',
            {'entity_ids': [parent.id], 'reason': 'gone'},
            format='json',
        )
        assert resp.status_code == 422
        parent.refresh_from_db()
        assert parent.status == 'active'

    def test_parent_and_child_together_succeeds(self, hierarchy_user, node_type):
        parent = _mk(node_type, 'P')
        child = _mk(node_type, 'CH', parent=parent)
        resp = _auth_client(hierarchy_user).post(
            f'{ENTITIES}/bulk-deactivate/',
            {'entity_ids': [parent.id, child.id], 'reason': 'gone'},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['deactivated'] == 2
        parent.refresh_from_db(); child.refresh_from_db()
        assert parent.status == 'inactive' and child.status == 'inactive'

    def test_cascade_deactivates_subtree(self, hierarchy_user, node_type):
        parent = _mk(node_type, 'P')
        child = _mk(node_type, 'CH', parent=parent)
        grandchild = _mk(node_type, 'GC', parent=child)
        resp = _auth_client(hierarchy_user).post(
            f'{ENTITIES}/bulk-deactivate/',
            {'entity_ids': [parent.id], 'reason': 'gone', 'cascade': True},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['deactivated'] == 3
        for e in (parent, child, grandchild):
            e.refresh_from_db()
            assert e.status == 'inactive'


# ── Bulk role assignment ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBulkRoles:

    def test_add_unions_with_existing(self, user_mgr):
        r1 = Role.objects.create(code='r1', name='R1', permissions={})
        r2 = Role.objects.create(code='r2', name='R2', permissions={})
        u1 = User.objects.create_user(email='u1@x.com')
        UserRole.objects.create(user=u1, role=r1, effective_from=date.today())
        u2 = User.objects.create_user(email='u2@x.com')

        resp = _auth_client(user_mgr).post(
            f'{USERS}/bulk-roles/',
            {'user_ids': [u1.id, u2.id], 'role_codes': ['r2'], 'mode': 'add'},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['updated'] == 2
        # u1 keeps r1 AND gains r2.
        assert set(u1.user_roles.filter(is_active=True).values_list('role__code', flat=True)) == {'r1', 'r2'}
        assert set(u2.user_roles.filter(is_active=True).values_list('role__code', flat=True)) == {'r2'}

    def test_replace_sets_exact_roles(self, user_mgr):
        r1 = Role.objects.create(code='r1', name='R1', permissions={})
        r2 = Role.objects.create(code='r2', name='R2', permissions={})
        u1 = User.objects.create_user(email='u1@x.com')
        UserRole.objects.create(user=u1, role=r1, effective_from=date.today())

        resp = _auth_client(user_mgr).post(
            f'{USERS}/bulk-roles/',
            {'user_ids': [u1.id], 'role_codes': ['r2'], 'mode': 'replace'},
            format='json',
        )
        assert resp.status_code == 200
        assert set(u1.user_roles.filter(is_active=True).values_list('role__code', flat=True)) == {'r2'}

    def test_unknown_role_code_rejected(self, user_mgr):
        u1 = User.objects.create_user(email='u1@x.com')
        resp = _auth_client(user_mgr).post(
            f'{USERS}/bulk-roles/',
            {'user_ids': [u1.id], 'role_codes': ['nope'], 'mode': 'add'},
            format='json',
        )
        assert resp.status_code == 422
        assert u1.user_roles.filter(is_active=True).count() == 0
