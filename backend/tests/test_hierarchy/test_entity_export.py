"""
Phase B3 — entity export + dynamic import template.

Covers: CSV export columns and filter honouring, flat per-field attribute
columns, round-trip (export → re-import recreates entities), and the
schema-driven import template.
"""
import csv
import io
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.hierarchy.models import Channel, Node, NodeType

EXPORT_URL = '/api/v1/entities/export/'
TEMPLATE_URL = '/api/v1/entities/import-template/'
BULK_URL = '/api/v1/entities/bulk/'


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
def dealer_type(db):
    """A non-loginable type with a mix of attribute field types."""
    return NodeType.objects.create(
        name='Dealer', code='DEALER', level_order=2, effective_from=date.today(),
        attribute_schema=[
            {'key': 'gst', 'label': 'GST', 'type': 'string', 'required': True},
            {'key': 'credit_limit', 'label': 'Credit Limit', 'type': 'decimal', 'required': False},
            {'key': 'store_class', 'label': 'Class', 'type': 'choice', 'required': False,
             'options': ['A', 'B', 'C']},
        ],
    )


def _body(response):
    """Exports stream (StreamingHttpResponse); templates don't. Read either."""
    if getattr(response, 'streaming', False):
        return b''.join(response.streaming_content).decode()
    return response.content.decode()


def _read_csv(response):
    return list(csv.DictReader(io.StringIO(_body(response))))


# ── Export ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNodeExport:

    def test_export_columns_and_attribute_spread(self, hierarchy_user, dealer_type):
        Node.objects.create(
            entity_type=dealer_type, name='Acme', code='ACME',
            attributes={'gst': '29ABCDE1234F1Z5', 'credit_limit': '50000', 'store_class': 'A'},
            effective_from=date.today(),
        )
        resp = _auth_client(hierarchy_user).get(EXPORT_URL)
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'text/csv'
        rows = _read_csv(resp)
        assert len(rows) == 1
        row = rows[0]
        # Reserved columns + one column per attribute key.
        for col in ('entity_type_code', 'name', 'code', 'parent_code',
                    'channel_code', 'geography_node_code', 'status', 'path',
                    'gst', 'credit_limit', 'store_class'):
            assert col in row
        assert row['entity_type_code'] == 'DEALER'
        assert row['gst'] == '29ABCDE1234F1Z5'
        assert row['store_class'] == 'A'

    def test_export_honours_type_filter(self, hierarchy_user, dealer_type):
        other = NodeType.objects.create(
            name='Distributor', code='DIST', level_order=1, effective_from=date.today(),
        )
        Node.objects.create(entity_type=dealer_type, name='D1', code='D1', effective_from=date.today())
        Node.objects.create(entity_type=other, name='X1', code='X1', effective_from=date.today())
        resp = _auth_client(hierarchy_user).get(f'{EXPORT_URL}?type=DEALER')
        rows = _read_csv(resp)
        assert {r['code'] for r in rows} == {'D1'}

    def test_export_round_trips(self, hierarchy_user, dealer_type):
        """Exported CSV re-imports cleanly and recreates the entity."""
        Node.objects.create(
            entity_type=dealer_type, name='Acme', code='ACME',
            attributes={'gst': '29ABCDE1234F1Z5', 'credit_limit': '50000', 'store_class': 'B'},
            effective_from=date.today(),
        )
        client = _auth_client(hierarchy_user)
        csv_text = _body(client.get(EXPORT_URL))

        # Wipe and re-import the exact exported file.
        Node.objects.all().delete()
        resp = client.post(BULK_URL, {'format': 'csv', 'data': csv_text}, format='json')
        assert resp.status_code == 200, resp.data
        assert resp.data['status'] == 'success'
        assert resp.data['created'] == 1

        recreated = Node.objects.get(code='ACME')
        assert recreated.entity_type_id == dealer_type.id
        assert recreated.attributes['gst'] == '29ABCDE1234F1Z5'
        assert recreated.attributes['store_class'] == 'B'


# ── Flat-column import + geography ─────────────────────────────────────────────

@pytest.mark.django_db
class TestFlatColumnImport:

    def test_flat_columns_map_to_attributes(self, hierarchy_user, dealer_type):
        csv_text = (
            'entity_type_code,name,code,gst,store_class\n'
            'DEALER,Beta,BETA,27PQRS5678G2Z1,C\n'
        )
        resp = _auth_client(hierarchy_user).post(
            BULK_URL, {'format': 'csv', 'data': csv_text}, format='json',
        )
        assert resp.status_code == 200, resp.data
        beta = Node.objects.get(code='BETA')
        assert beta.attributes == {'gst': '27PQRS5678G2Z1', 'store_class': 'C'}

    def test_missing_required_flat_column_rejected(self, hierarchy_user, dealer_type):
        # gst is required; omit it.
        csv_text = 'entity_type_code,name,code,store_class\nDEALER,Beta,BETA,A\n'
        resp = _auth_client(hierarchy_user).post(
            BULK_URL, {'format': 'csv', 'data': csv_text}, format='json',
        )
        assert resp.status_code == 422
        assert resp.data['status'] == 'validation_failed'
        assert not Node.objects.filter(code='BETA').exists()


# ── Import template ───────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestImportTemplate:

    def test_template_columns_match_schema(self, hierarchy_user, dealer_type):
        resp = _auth_client(hierarchy_user).get(f'{TEMPLATE_URL}?entity_type=DEALER')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'text/csv'
        reader = list(csv.reader(io.StringIO(resp.content.decode())))
        header, sample = reader[0], reader[1]
        assert header == [
            'entity_type_code', 'name', 'code', 'parent_code',
            'channel_code', 'geography_node_code', 'gst', 'credit_limit', 'store_class',
        ]
        # Sample row pre-fills the type code and shows the choice option.
        sample_map = dict(zip(header, sample))
        assert sample_map['entity_type_code'] == 'DEALER'
        assert sample_map['store_class'] == 'A'

    def test_unknown_type_returns_422(self, hierarchy_user):
        resp = _auth_client(hierarchy_user).get(f'{TEMPLATE_URL}?entity_type=NOPE')
        assert resp.status_code == 422

    def test_template_round_trips_through_import(self, hierarchy_user, dealer_type):
        """A filled-in template imports cleanly."""
        client = _auth_client(hierarchy_user)
        tmpl = client.get(f'{TEMPLATE_URL}?entity_type=DEALER').content.decode()
        rows = list(csv.DictReader(io.StringIO(tmpl)))
        row = rows[0]
        row['name'] = 'Gamma'
        row['code'] = 'GAMMA'
        row['gst'] = '29ZZZZZ0000Z0Z0'
        row['credit_limit'] = ''  # optional
        row['store_class'] = 'B'

        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)

        resp = client.post(BULK_URL, {'format': 'csv', 'data': out.getvalue()}, format='json')
        assert resp.status_code == 200, resp.data
        gamma = Node.objects.get(code='GAMMA')
        assert gamma.attributes['store_class'] == 'B'
        assert 'credit_limit' not in gamma.attributes  # empty cell omitted
