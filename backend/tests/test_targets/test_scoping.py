"""Target allocations scope to the territories the requester owns (geography-canonical);
the per-user person-view still respects the org subtree."""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetAllocation, TargetPeriod

ALLOC_URL = '/api/v1/targets/allocations/'
PERSON_URL = '/api/v1/targets/allocations/person-view/'


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return client


def _role(level):
    return Role.objects.create(code=f'tgt_{level}', name=level, permissions={'target_management': level})


def _user(email, *, entity=None, level=None):
    u = User.objects.create_user(email=email, password='pass', entity=entity)
    if level:
        UserRole.objects.create(user=u, role=_role(level), effective_from=date.today())
    return u


@pytest.fixture
def setup(db):
    et = NodeType.objects.create(name='Node', code='NODE', level_order=1, effective_from=date.today())
    root = Node.objects.create(entity_type=et, name='Root', code='ROOT', effective_from=date.today())
    a = Node.objects.create(entity_type=et, name='A', code='A', parent=root, effective_from=date.today())
    b = Node.objects.create(entity_type=et, name='B', code='B', parent=root, effective_from=date.today())

    gt = GeographyType.objects.create(name='Geo', code='geo', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='Region', code='REGION', level='region')
    town_a = GeographyNode.objects.create(geography_type=gt, name='TownA', code='TOWNA', level='town', parent=region)
    town_b = GeographyNode.objects.create(geography_type=gt, name='TownB', code='TOWNB', level='town', parent=region)
    for ent, node in ((root, region), (a, town_a), (b, town_b)):
        AssignmentService.create(assignee_id=ent.id, scope_id=node.id, effective_from=date(2025, 1, 1))

    kpi = KPIDefinition.objects.create(code='K', name='K', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
                                       measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'})
    period = TargetPeriod.objects.create(code='P', name='P', period_type=TargetPeriod.MONTHLY,
                                         start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))
    for node in (town_a, town_b):
        TargetAllocation.objects.create(target_period=period, kpi=kpi, geography_node=node,
                                        target_value=Decimal('1000'), original_target_value=Decimal('1000'))
    return {'root': root, 'a': a, 'b': b, 'town_a': town_a, 'town_b': town_b, 'kpi': kpi, 'period': period}


def test_allocation_list_scoped_to_owned_territory(setup):
    u = _user('a@x.com', entity=setup['a'], level='view_all')
    resp = _auth(u).get(ALLOC_URL)
    assert resp.status_code == 200
    assert {row['geography_node'] for row in resp.data['results']} == {setup['town_a'].id}


def test_root_user_sees_all_allocations(setup):
    u = _user('r@x.com', entity=setup['root'], level='team')
    resp = _auth(u).get(ALLOC_URL)
    assert {row['geography_node'] for row in resp.data['results']} == {setup['town_a'].id, setup['town_b'].id}


def test_allocation_collection_post_is_405(setup):
    # Allocations are only ever written through plan commits / governed revisions —
    # the collection endpoint must refuse a bare POST cleanly, not 500 into a raw create.
    u = _user('r@x.com', entity=setup['root'], level='full')
    resp = _auth(u).post(ALLOC_URL, {'target_value': '1'}, format='json')
    assert resp.status_code == 405


def test_person_view_within_subtree_ok(setup):
    u = _user('a@x.com', entity=setup['a'], level='view_all')
    resp = _auth(u).get(PERSON_URL, {'period_id': setup['period'].id, 'kpi_id': setup['kpi'].id,
                                     'entity_id': setup['a'].id})
    assert resp.status_code == 200
    assert resp.data['entity_id'] == setup['a'].id
    assert Decimal(resp.data['target']) == Decimal('1000')


def test_person_view_outside_subtree_blocked(setup):
    # A manager at A cannot view B's rolled-up target.
    u = _user('a@x.com', entity=setup['a'], level='view_all')
    resp = _auth(u).get(PERSON_URL, {'period_id': setup['period'].id, 'kpi_id': setup['kpi'].id,
                                     'entity_id': setup['b'].id})
    assert resp.status_code == 422  # BusinessError → 422


# ── planning-admin gate: calendar + versioned config are HO-only ────────────────
_CONFIG_POSTS = [
    ('/api/v1/targets/periods/', {'code': 'NEW', 'name': 'New', 'period_type': 'monthly',
                                  'start_date': '2026-07-01', 'end_date': '2026-07-31'}),
    ('/api/v1/targets/periods/generate-year/', {'fiscal_year': '2098-99', 'start_month': 4}),
    ('/api/v1/targets/recipes/', {'name': 'R', 'code': 'R',
                                  'weight_components': [{'source': 'equal'}]}),
    ('/api/v1/targets/revision-policies/', {'name': 'P', 'code': 'P'}),
]


def test_placed_user_cannot_mutate_calendar_or_planning_config(setup):
    """A field user (placed in the org tree) can read but never administer the planning
    calendar, recipes or change caps — regardless of their write level."""
    u = _user('asm@x.com', entity=setup['a'], level='team')
    client = _auth(u)
    for url, body in _CONFIG_POSTS:
        assert client.post(url, body, format='json').status_code == 422, url
    # Reads stay open (the person tab needs the period tree).
    assert client.get('/api/v1/targets/periods/').status_code == 200


def test_ho_admin_can_mutate_calendar_and_planning_config(setup):
    u = _user('ho@x.com', level='full')  # no home entity → planning admin
    client = _auth(u)
    for url, body in _CONFIG_POSTS:
        resp = client.post(url, body, format='json')
        assert resp.status_code == 201, (url, resp.data)
