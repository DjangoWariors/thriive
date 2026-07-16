"""
Phase B5 — list scale & consistency.

Node list pagination, ordering, and an N+1 guard (constant query count
regardless of row count).
"""
from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.hierarchy.models import Node, NodeType

ENTITIES = '/api/v1/entities/'


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
def node_type(db):
    return NodeType.objects.create(name='Node', code='NODE', level_order=1, effective_from=date.today())


def _mk(node_type, code, parent=None):
    return Node.objects.create(
        entity_type=node_type, name=code, code=code, parent=parent, effective_from=date.today(),
    )


@pytest.mark.django_db
class TestNodeListScale:

    def test_list_is_paginated(self, hierarchy_user, node_type):
        for i in range(30):
            _mk(node_type, f'N{i:03d}')
        resp = _auth_client(hierarchy_user).get(ENTITIES)
        assert resp.status_code == 200
        assert resp.data['count'] == 30
        assert len(resp.data['results']) == 25  # default page size
        assert resp.data['next'] is not None

    def test_page_size_param(self, hierarchy_user, node_type):
        for i in range(10):
            _mk(node_type, f'N{i:03d}')
        resp = _auth_client(hierarchy_user).get(f'{ENTITIES}?page_size=5')
        assert len(resp.data['results']) == 5

    def test_default_ordering_by_name(self, hierarchy_user, node_type):
        _mk(node_type, 'ZED')
        _mk(node_type, 'ALPHA')
        _mk(node_type, 'MIKE')
        resp = _auth_client(hierarchy_user).get(ENTITIES)
        names = [r['name'] for r in resp.data['results']]
        assert names == ['ALPHA', 'MIKE', 'ZED']

    def test_ordering_param_descending(self, hierarchy_user, node_type):
        _mk(node_type, 'A')
        _mk(node_type, 'B')
        _mk(node_type, 'C')
        resp = _auth_client(hierarchy_user).get(f'{ENTITIES}?ordering=-code')
        codes = [r['code'] for r in resp.data['results']]
        assert codes == ['C', 'B', 'A']

    def test_no_n_plus_one_queries(self, hierarchy_user, node_type):
        """Listing more rows must not issue more queries."""
        client = _auth_client(hierarchy_user)

        for i in range(3):
            _mk(node_type, f'A{i}')
        with CaptureQueriesContext(connection) as small:
            client.get(f'{ENTITIES}?page_size=100')

        for i in range(20):
            _mk(node_type, f'B{i:02d}')
        with CaptureQueriesContext(connection) as large:
            client.get(f'{ENTITIES}?page_size=100')

        assert len(small.captured_queries) == len(large.captured_queries)

    def test_root_filter_returns_only_parentless(self, hierarchy_user, node_type):
        root = _mk(node_type, 'ROOT')
        _mk(node_type, 'CHILD', parent=root)
        resp = _auth_client(hierarchy_user).get(f'{ENTITIES}?root=true')
        assert resp.status_code == 200
        codes = {r['code'] for r in resp.data['results']}
        assert codes == {'ROOT'}

    def test_counts_endpoint(self, hierarchy_user, node_type):
        other = NodeType.objects.create(
            name='Leaf', code='LEAF', level_order=2, effective_from=date.today(),
        )
        root = _mk(node_type, 'ROOT')
        Node.objects.create(entity_type=other, name='L1', code='L1', parent=root,
                              effective_from=date.today())
        Node.objects.create(entity_type=other, name='L2', code='L2', parent=root,
                              effective_from=date.today())
        resp = _auth_client(hierarchy_user).get(f'{ENTITIES}counts/')
        assert resp.status_code == 200
        assert resp.data['counts'] == {'NODE': 1, 'LEAF': 2}
        assert resp.data['total'] == 3

    def test_children_and_subtree_are_paginated(self, hierarchy_user, node_type):
        root = _mk(node_type, 'ROOT')
        for i in range(30):
            _mk(node_type, f'C{i:03d}', parent=root)
        children = _auth_client(hierarchy_user).get(f'{ENTITIES}{root.id}/children/')
        assert children.data['count'] == 30
        assert len(children.data['results']) == 25
        subtree = _auth_client(hierarchy_user).get(f'{ENTITIES}{root.id}/subtree/')
        assert subtree.data['count'] == 30
        assert len(subtree.data['results']) == 25
