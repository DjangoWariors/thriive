from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.exceptions import BusinessError
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.kpi_engine.services import KPIService


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser(email='kpi_admin@test.com', password='x')
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _value_kpi_data(code='SALES'):
    return {
        'code': code, 'name': 'Sales', 'kpi_type': KPIDefinition.VALUE,
        'measure_config': {'measure_field': 'net_amount', 'aggregation': 'sum',
                           'net_logic': 'sales_minus_returns'},
    }


# ── config validation ────────────────────────────────────────────────────────
def test_value_kpi_requires_sum(db):
    data = _value_kpi_data()
    data['measure_config']['aggregation'] = 'count'
    errors = KPIService.validate_kpi_config(data)
    assert any('sum' in e for e in errors)


def test_ratio_requires_numerator_and_denominator(db):
    errors = KPIService.validate_kpi_config({'code': 'R', 'kpi_type': KPIDefinition.RATIO, 'ratio_config': {}})
    assert any('numerator' in e for e in errors)
    assert any('denominator' in e for e in errors)


def test_growth_requires_valid_basis(db):
    errors = KPIService.validate_kpi_config({
        'code': 'G', 'kpi_type': KPIDefinition.GROWTH, 'growth_config': {'basis': 'bogus'},
        'measure_config': {'measure_field': 'net_amount', 'aggregation': 'sum'},
    })
    assert any('basis' in e for e in errors)


def test_composite_unknown_reference_rejected(db):
    errors = KPIService.validate_kpi_config({
        'code': 'C', 'kpi_type': KPIDefinition.COMPOSITE,
        'composite_config': {'expression': 'A + B'},
    })
    assert any('unknown KPI code' in e for e in errors)


def test_composite_self_reference_rejected(db):
    KPIService.create_kpi(_value_kpi_data('A'))
    errors = KPIService.validate_kpi_config({
        'code': 'SELF', 'kpi_type': KPIDefinition.COMPOSITE,
        'composite_config': {'expression': 'SELF + A'},
    })
    assert any('itself' in e for e in errors)


def test_explicit_sku_filter_unknown_codes_rejected(db):
    from apps.master_data.models import SKU
    SKU.objects.create(code='SKU1', name='One')
    data = _value_kpi_data('EXPL')
    data['sku_filter'] = {'type': 'explicit', 'sku_codes': ['SKU1', 'NOPE']}
    errors = KPIService.validate_kpi_config(data)
    assert any('Unknown SKU code' in e and 'NOPE' in e and 'SKU1' not in e for e in errors)


def test_explicit_sku_filter_known_codes_ok(db):
    from apps.master_data.models import SKU
    SKU.objects.create(code='SKU1', name='One')
    data = _value_kpi_data('EXPL2')
    data['sku_filter'] = {'type': 'explicit', 'sku_codes': ['SKU1']}
    errors = KPIService.validate_kpi_config(data)
    assert not any('SKU code' in e for e in errors)


# ── versioning ───────────────────────────────────────────────────────────────
def test_update_creates_new_version(db):
    kpi = KPIService.create_kpi(_value_kpi_data('VER'))
    assert kpi.version == 1
    KPIService.update_kpi(kpi, {'name': 'Renamed', 'unit': '₹'})
    kpi.refresh_from_db()
    assert kpi.version == 2 and kpi.is_current is True and kpi.name == 'Renamed'
    old = KPIDefinition.objects.get(code='VER', version=1)
    assert old.is_current is False


def test_create_duplicate_code_rejected(db):
    KPIService.create_kpi(_value_kpi_data('DUP'))
    with pytest.raises(BusinessError):
        KPIService.create_kpi(_value_kpi_data('DUP'))


# ── transaction import idempotency ───────────────────────────────────────────
CSV = (
    'attributed_node_id,transaction_date,transaction_type,transaction_level,channel_code,'
    'sku_code,outlet_code,bill_ref,gross_amount,net_amount,quantity,uom,source,external_ref\n'
    '101,2026-06-01,sale,secondary,GT,S1,OUT1,B1,1000,900,5,cases,dms_sync,DMS-1\n'
    '101,2026-06-01,sale,secondary,GT,S2,OUT1,B1,500,450,2,cases,dms_sync,DMS-2\n'
)


def test_bulk_import_then_reimport_is_idempotent(db):
    first = KPIService.bulk_import_transactions(CSV)
    assert first['status'] == 'success' and first['created'] == 2
    assert Transaction.objects.count() == 2

    second = KPIService.bulk_import_transactions(CSV)  # same (source, external_ref)
    assert second['updated'] == 2 and second['created'] == 0
    assert Transaction.objects.count() == 2  # no duplicates


def test_bulk_import_validation_is_all_or_nothing(db):
    bad = CSV + '101,not-a-date,sale,secondary,GT,S3,OUT1,B2,100,90,1,cases,dms_sync,DMS-3\n'
    result = KPIService.bulk_import_transactions(bad)
    assert result['status'] == 'validation_failed'
    assert Transaction.objects.count() == 0  # nothing written


# ── API smoke ────────────────────────────────────────────────────────────────
def test_api_create_and_list(admin_client):
    resp = admin_client.post('/api/v1/kpis/definitions/', _value_kpi_data('API1'), format='json')
    assert resp.status_code == 201, resp.content
    resp = admin_client.get('/api/v1/kpis/definitions/')
    assert resp.status_code == 200
    codes = [row['code'] for row in resp.json()['results']]
    assert 'API1' in codes


def test_api_edit_kpi_already_on_v2_succeeds(admin_client):
    """Regression: a read-only `version` made DRF's auto (code, version) validator
    filter on the model default (1), so editing a KPI already on v2+ falsely tripped
    'The fields code, version must make a unique set.'"""
    create = admin_client.post('/api/v1/kpis/definitions/', _value_kpi_data('EDIT2'), format='json')
    assert create.status_code == 201, create.content
    kpi_id = create.json()['id']

    # First edit → v2
    first = admin_client.put(f'/api/v1/kpis/definitions/{kpi_id}/', {**_value_kpi_data('EDIT2'), 'name': 'V2'}, format='json')
    assert first.status_code == 200, first.content
    assert first.json()['version'] == 2

    # Second edit on the now-v2 record → must still validate and bump to v3
    cur = KPIDefinition.objects.get(code='EDIT2', is_current=True)
    second = admin_client.put(f'/api/v1/kpis/definitions/{cur.id}/', {**_value_kpi_data('EDIT2'), 'name': 'V3'}, format='json')
    assert second.status_code == 200, second.content
    assert second.json()['version'] == 3 and second.json()['name'] == 'V3'


def test_api_validate_endpoint(admin_client):
    bad = _value_kpi_data('BAD')
    bad['measure_config']['aggregation'] = 'count'
    resp = admin_client.post('/api/v1/kpis/definitions/validate/', bad, format='json')
    assert resp.status_code == 200
    assert resp.json()['valid'] is False


def test_api_preview_endpoint(admin_client, db):
    from apps.assignments.services import AssignmentService
    from apps.hierarchy.models import Node, NodeType, GeographyNode, GeographyType
    et = NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())
    entity = Node.objects.create(entity_type=et, name='ASE', code='ASE9', effective_from=date.today())
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['town'])
    node = GeographyNode.objects.create(geography_type=gt, name='Town', code='TOWN9', level='town')
    AssignmentService.create(assignee_id=entity.id, scope_id=node.id, effective_from=date(2025, 1, 1))
    Transaction.objects.create(
        attributed_node_id=node.id, transaction_date=date(2026, 6, 10), transaction_type=Transaction.SALE,
        transaction_level=Transaction.SECONDARY, channel_code='GT', net_amount=Decimal('2500'),
    )
    payload = {
        'config': _value_kpi_data('PREV'),
        'entity_id': entity.id, 'period_start': '2026-06-01', 'period_end': '2026-06-30',
    }
    resp = admin_client.post('/api/v1/kpis/definitions/preview/', payload, format='json')
    assert resp.status_code == 200, resp.content
    assert resp.json()['result'] == '2500.00'
