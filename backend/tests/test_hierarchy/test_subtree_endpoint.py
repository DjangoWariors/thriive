"""
Subtree endpoint — the /api/v1/entities/{id}/subtree/ action returns all
descendants and now carries each row's linked user (if the type is loginable),
which the entity-detail "View full page" table consumes.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.hierarchy.models import Node, NodeType


def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


@pytest.fixture
def hierarchy_user(db):
    user = User.objects.create_user(email='hmgr@example.com', password='pass')
    role = Role.objects.create(
        code='hier_mgr', name='Hierarchy Manager',
        permissions={'hierarchy_management': 'full'},
    )
    UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


@pytest.fixture
def login_type(db):
    return NodeType.objects.create(
        name='Manager', code='MGR', level_order=1,
        is_loginable=True, effective_from=date.today(),
    )


@pytest.fixture
def plain_type(db):
    return NodeType.objects.create(
        name='Outlet', code='OUTLET', level_order=2,
        is_loginable=False, effective_from=date.today(),
    )


@pytest.mark.django_db
def test_subtree_returns_descendants_with_linked_user(hierarchy_user, login_type, plain_type):
    root = Node.objects.create(entity_type=login_type, name='Root', code='ROOT',
                                 effective_from=date.today())
    child = Node.objects.create(entity_type=login_type, name='Child', code='CHILD',
                                  parent=root, effective_from=date.today())
    User.objects.create_user(email='child@example.com', password='pass', entity=child)
    gc = Node.objects.create(entity_type=plain_type, name='Outlet1', code='GC',
                               parent=child, effective_from=date.today())

    resp = _auth_client(hierarchy_user).get(f'/api/v1/entities/{root.id}/subtree/')
    assert resp.status_code == 200

    # Subtree is paginated (can be tens of thousands of rows at scale).
    results = resp.data['results']
    rows = {r['code']: r for r in results}
    # Descendants only — root itself is excluded.
    assert set(rows) == {'CHILD', 'GC'}
    # Every row exposes the linked_user key.
    assert all('linked_user' in r for r in results)
    # Loginable descendant carries its user; non-login one is null.
    assert rows['CHILD']['linked_user']['email'] == 'child@example.com'
    assert rows[gc.code]['linked_user'] is None
