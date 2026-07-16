"""P2 workspace API filters: assignments ?q= and geography nodes ?levels=."""
from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType

TODAY = date.today()


@pytest.fixture
def admin(db):
    return User.objects.create_superuser(email='admin@example.com', password='x')


@pytest.fixture
def client(admin):
    c = APIClient()
    c.force_authenticate(user=admin)
    return c


@pytest.fixture
def world(db):
    et = NodeType.objects.create(name='ASM', code='ASM', level_order=3, effective_from=TODAY)
    gt = GeographyType.objects.create(name='Geo', code='geo', levels=['nation', 'town'])
    nation = GeographyNode.objects.create(geography_type=gt, name='India', code='IN', level='nation')
    town = GeographyNode.objects.create(geography_type=gt, name='Karol Bagh', code='KB', level='town', parent=nation)
    anjali = Node.objects.create(entity_type=et, name='Anjali Gupta', code='ASM-0001', effective_from=TODAY)
    Assignment.objects.create(assignee=anjali, scope=town, role_in_scope='owner', effective_from=TODAY)
    Assignment.objects.create(
        assignee=Node.objects.create(entity_type=et, name='Ravi Verma', code='ASM-0002', effective_from=TODAY),
        scope=nation, role_in_scope='owner', effective_from=TODAY,
    )
    return {'town': town, 'nation': nation}


@pytest.mark.django_db
def test_assignments_q_matches_assignee_name(client, world):
    resp = client.get('/api/v1/assignments/', {'q': 'anjali'})
    assert resp.status_code == 200
    assert [r['assignee']['name'] for r in resp.data['results']] == ['Anjali Gupta']


@pytest.mark.django_db
def test_assignments_q_matches_scope_code(client, world):
    resp = client.get('/api/v1/assignments/', {'q': 'KB'})
    assert resp.status_code == 200
    assert [r['scope']['code'] for r in resp.data['results']] == ['KB']


@pytest.mark.django_db
def test_geography_levels_csv_filter(client, world):
    resp = client.get('/api/v1/geography/nodes/', {'type': 'geo', 'levels': 'nation,town'})
    assert {r['code'] for r in resp.data['results']} == {'IN', 'KB'}
    resp = client.get('/api/v1/geography/nodes/', {'type': 'geo', 'levels': 'nation'})
    assert {r['code'] for r in resp.data['results']} == {'IN'}
