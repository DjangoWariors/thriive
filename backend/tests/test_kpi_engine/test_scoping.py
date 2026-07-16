"""Transaction list endpoint is territory-scoped: sales attach to geography, so a placed
user sees the transactions of the territories they own (via assignments), not an org subtree."""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Node, NodeType, GeographyNode, GeographyType
from apps.kpi_engine.models import Transaction

TXN_URL = '/api/v1/kpis/transactions/'


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return client


def _role(level):
    return Role.objects.create(code=f'kpi_{level}', name=level, permissions={'kpi_definitions': level})


def _user(email, *, entity=None, level=None):
    u = User.objects.create_user(email=email, password='pass', entity=entity)
    if level:
        UserRole.objects.create(user=u, role=_role(level), effective_from=date.today())
    return u


@pytest.fixture
def tree(db):
    """Org root→{a,b}; geography region→{townA,townB}; root owns the region, a/b own a town each.
    One transaction is booked in each town."""
    t = NodeType.objects.create(name='Node', code='NODE', level_order=1, effective_from=date.today())
    root = Node.objects.create(entity_type=t, name='Root', code='ROOT', effective_from=date.today())
    a = Node.objects.create(entity_type=t, name='A', code='A', parent=root, effective_from=date.today())
    b = Node.objects.create(entity_type=t, name='B', code='B', parent=root, effective_from=date.today())

    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='Region', code='REGION', level='region')
    town_a = GeographyNode.objects.create(geography_type=gt, name='TownA', code='TOWNA', level='town', parent=region)
    town_b = GeographyNode.objects.create(geography_type=gt, name='TownB', code='TOWNB', level='town', parent=region)

    AssignmentService.create(assignee_id=root.id, scope_id=region.id, effective_from=date(2025, 1, 1))
    AssignmentService.create(assignee_id=a.id, scope_id=town_a.id, effective_from=date(2025, 1, 1))
    AssignmentService.create(assignee_id=b.id, scope_id=town_b.id, effective_from=date(2025, 1, 1))

    for node in (town_a, town_b):
        Transaction.objects.create(attributed_node_id=node.id, transaction_date=date(2026, 6, 1),
                                   transaction_type=Transaction.SALE, net_amount=Decimal('100'))
    return {'root': root, 'a': a, 'b': b, 'region': region, 'town_a': town_a, 'town_b': town_b}


def _node_ids(resp):
    assert resp.status_code == 200, resp.data
    return {row['attributed_node_id'] for row in resp.data['results']}


def test_manager_sees_only_own_territory_transactions(tree):
    u = _user('a@x.com', entity=tree['a'], level='view_all')  # view_all STILL scoped to owned territory
    assert _node_ids(_auth(u).get(TXN_URL)) == {tree['town_a'].id}


def test_root_user_sees_whole_owned_region(tree):
    u = _user('r@x.com', entity=tree['root'], level='team')
    assert _node_ids(_auth(u).get(TXN_URL)) == {tree['town_a'].id, tree['town_b'].id}


def test_superuser_sees_all(tree):
    su = User.objects.create_superuser(email='su@x.com', password='pass')
    assert _node_ids(_auth(su).get(TXN_URL)) == {tree['town_a'].id, tree['town_b'].id}


def test_standalone_admin_sees_all(tree):
    u = _user('admin@x.com', entity=None, level='full')
    assert _node_ids(_auth(u).get(TXN_URL)) == {tree['town_a'].id, tree['town_b'].id}
