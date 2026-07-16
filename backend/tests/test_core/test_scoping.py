"""
Node-scope filtering of list endpoints (NodeScopedQuerysetMixin).

Platform rule: anyone placed in the entity hierarchy sees ONLY their own entity
and its descendants (entity.path subtree) — for every hierarchy data endpoint,
regardless of permission level. Superusers bypass. Users with no linked entity
(standalone admin/finance) fall back to their level: read-any sees all, else none.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.hierarchy.models import Node, NodeType

ENTITIES_URL = '/api/v1/entities/'
SEARCH_URL = '/api/v1/entities/search/'
USERS_URL = '/api/v1/auth/users/'


def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


def _role(perm, level):
    return Role.objects.create(
        code=f'{perm}_{level}', name=f'{perm} {level}',
        permissions={perm: level},
    )


def _user(email, *, entity=None, role=None):
    u = User.objects.create_user(email=email, password='pass', entity=entity)
    if role is not None:
        UserRole.objects.create(user=u, role=role, effective_from=date.today())
    return u


@pytest.fixture
def node_type(db):
    return NodeType.objects.create(
        name='Node', code='NODE', level_order=1, effective_from=date.today(),
    )


@pytest.fixture
def tree(node_type):
    """/ROOT/ → /ROOT/A/ → /ROOT/A/A1/ , plus /ROOT/B/."""
    root = Node.objects.create(entity_type=node_type, name='Root', code='ROOT',
                                 effective_from=date.today())
    a = Node.objects.create(entity_type=node_type, name='A', code='A',
                              parent=root, effective_from=date.today())
    a1 = Node.objects.create(entity_type=node_type, name='A1', code='A1',
                               parent=a, effective_from=date.today())
    b = Node.objects.create(entity_type=node_type, name='B', code='B',
                              parent=root, effective_from=date.today())
    return {'root': root, 'a': a, 'a1': a1, 'b': b}


def _codes(resp):
    assert resp.status_code == 200, resp.data
    return {row['code'] for row in resp.data['results']}


# ── Node list scoping: subtree regardless of level ────────────────────────

@pytest.mark.django_db
class TestNodeListScope:

    @pytest.mark.parametrize('level', ['team', 'own_only', 'view_edit', 'view_all', 'full'])
    def test_mid_node_sees_own_subtree(self, tree, level):
        # A user placed at A sees A + A1, never ROOT or B — whatever the level.
        u = _user('a@x.com', entity=tree['a'], role=_role('hierarchy_management', level))
        assert _codes(_auth_client(u).get(ENTITIES_URL)) == {'A', 'A1'}

    def test_leaf_sees_only_self(self, tree):
        # A1 is a leaf — its subtree is just itself, even with view_all.
        u = _user('leaf@x.com', entity=tree['a1'], role=_role('hierarchy_management', 'view_all'))
        assert _codes(_auth_client(u).get(ENTITIES_URL)) == {'A1'}

    def test_root_node_sees_whole_tree(self, tree):
        # A user at ROOT naturally sees everything (their subtree is the tree).
        u = _user('root@x.com', entity=tree['root'], role=_role('hierarchy_management', 'team'))
        assert _codes(_auth_client(u).get(ENTITIES_URL)) == {'ROOT', 'A', 'A1', 'B'}

    def test_superuser_sees_everything(self, tree):
        su = User.objects.create_superuser(email='su@x.com', password='pass')
        assert _codes(_auth_client(su).get(ENTITIES_URL)) == {'ROOT', 'A', 'A1', 'B'}

    def test_no_entity_readany_sees_all(self, tree):
        # Standalone admin (no hierarchy placement) with a read-any level.
        u = _user('admin@x.com', entity=None, role=_role('hierarchy_management', 'full'))
        assert _codes(_auth_client(u).get(ENTITIES_URL)) == {'ROOT', 'A', 'A1', 'B'}

    def test_no_entity_team_sees_nothing(self, tree):
        # team/own_only without a placement has no subtree to resolve.
        u = _user('noent@x.com', entity=None, role=_role('hierarchy_management', 'team'))
        assert _codes(_auth_client(u).get(ENTITIES_URL)) == set()

    def test_search_is_scoped(self, tree):
        u = _user('s@x.com', entity=tree['a'], role=_role('hierarchy_management', 'view_all'))
        resp = _auth_client(u).get(SEARCH_URL, {'q': ''})
        assert resp.status_code == 200
        assert {row['code'] for row in resp.data} == {'A', 'A1'}


# ── Detail/subtree access follows the scoped queryset ───────────────────────

@pytest.mark.django_db
class TestObjectAccess:

    def test_in_branch_subtree_ok(self, tree):
        u = _user('m@x.com', entity=tree['a'], role=_role('hierarchy_management', 'view_all'))
        resp = _auth_client(u).get(f"{ENTITIES_URL}{tree['a'].id}/subtree/")
        assert resp.status_code == 200
        assert {row['code'] for row in resp.data['results']} == {'A1'}

    def test_out_of_branch_retrieve_denied(self, tree):
        # B is outside A's subtree → absent from the scoped queryset → 404.
        u = _user('m2@x.com', entity=tree['a'], role=_role('hierarchy_management', 'view_all'))
        resp = _auth_client(u).get(f"{ENTITIES_URL}{tree['b'].id}/")
        assert resp.status_code in (403, 404)


# ── User list scoping ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestUserListScope:

    def test_user_sees_only_in_branch_users(self, tree):
        # Distinct entities (entity is OneToOne). Requester at A; u_a1 in-branch, u_b out.
        _user('u_a1@x.com', entity=tree['a1'])
        _user('u_b@x.com', entity=tree['b'])
        # view_all must STILL be scoped to the requester's subtree.
        requester = _user('uadmin@x.com', entity=tree['a'], role=_role('user_management', 'view_all'))

        resp = _auth_client(requester).get(USERS_URL, {'status': 'all'})
        assert resp.status_code == 200
        emails = {row['email'] for row in resp.data['results']}
        assert 'u_a1@x.com' in emails
        assert 'uadmin@x.com' in emails
        assert 'u_b@x.com' not in emails

    def test_no_entity_admin_sees_all_users(self, tree):
        _user('v_a1@x.com', entity=tree['a1'])
        _user('v_b@x.com', entity=tree['b'])
        requester = _user('vadmin@x.com', entity=None, role=_role('user_management', 'full'))
        resp = _auth_client(requester).get(USERS_URL, {'status': 'all'})
        emails = {row['email'] for row in resp.data['results']}
        assert {'v_a1@x.com', 'v_b@x.com', 'vadmin@x.com'} <= emails
