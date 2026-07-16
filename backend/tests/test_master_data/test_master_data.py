import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.exceptions import BusinessError
from apps.master_data.models import SKU, UOMConversion
from apps.master_data.services import MasterDataService


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser(email='md_admin@test.com', password='x')
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def noperm_client(db):
    """An authenticated user with no roles → no master_data permission."""
    user = User.objects.create_user(email='md_nobody@test.com', password='x')
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def skus(db):
    return [
        MasterDataService.create_sku({'code': 'A1', 'name': 'Alpha', 'brand': 'Acme', 'category': 'Tools', 'is_focus': True}),
        MasterDataService.create_sku({'code': 'A2', 'name': 'Beta', 'brand': 'Acme', 'category': 'Parts'}),
        MasterDataService.create_sku({'code': 'G1', 'name': 'Gamma', 'brand': 'Globex', 'category': 'Tools', 'is_focus': True}),
    ]


# ── SKU CRUD (service) ───────────────────────────────────────────────────────

def test_create_sku(db):
    sku = MasterDataService.create_sku({'code': 'X1', 'name': 'Widget', 'mrp': '99.50'})
    assert sku.pk is not None
    assert str(sku.mrp) == '99.50'


def test_create_sku_duplicate_code_rejected(db):
    MasterDataService.create_sku({'code': 'DUP', 'name': 'One'})
    with pytest.raises(BusinessError):
        MasterDataService.create_sku({'code': 'DUP', 'name': 'Two'})


def test_update_sku(db):
    sku = MasterDataService.create_sku({'code': 'U1', 'name': 'Old', 'is_focus': False})
    MasterDataService.update_sku(sku, {'name': 'New', 'is_focus': True})
    sku.refresh_from_db()
    assert sku.name == 'New' and sku.is_focus is True


def test_sku_group_rule_filters_on_attributes(db):
    from apps.master_data.models import SKUGroup
    MasterDataService.create_sku({'code': 'L1', 'name': 'Large', 'attributes': {'pack_size': 'large'}})
    MasterDataService.create_sku({'code': 'S1', 'name': 'Small', 'attributes': {'pack_size': 'small'}})
    group = SKUGroup.objects.create(
        code='LARGE', name='Large packs', filter_type=SKUGroup.FILTER_RULE,
        filter_rules={'attributes': {'pack_size': 'large'}},
    )
    codes = list(group.get_skus().values_list('code', flat=True))
    assert codes == ['L1']


# ── Bulk import upsert by code ───────────────────────────────────────────────

def test_bulk_import_upsert_by_code(db):
    MasterDataService.create_sku({'code': 'B1', 'name': 'Existing', 'mrp': '10'})
    csv_text = (
        'code,name,brand,category,mrp,is_focus,is_npi\n'
        'B1,Existing Updated,Acme,Tools,25,true,false\n'
        'B2,Brand New,Acme,Tools,,false,true\n'
    )
    result = MasterDataService.bulk_import_skus(csv_text)
    assert result['status'] == 'success'
    assert result['created'] == 1 and result['updated'] == 1
    b1 = SKU.objects.get(code='B1')
    assert b1.name == 'Existing Updated' and str(b1.mrp) == '25.00'
    assert SKU.objects.filter(code='B2').exists()


def test_bulk_import_all_or_nothing(db):
    csv_text = 'code,name\nOK1,Good\n,Missing Code\n'
    result = MasterDataService.bulk_import_skus(csv_text)
    assert result['status'] == 'validation_failed'
    assert result['errors']
    assert not SKU.objects.filter(code='OK1').exists()


# ── SKU Group — both filter types ────────────────────────────────────────────

def test_explicit_group_resolves_to_fixed_list(skus):
    group = MasterDataService.create_sku_group({
        'name': 'Picks', 'code': 'GP', 'filter_type': 'explicit', 'skus': [skus[0], skus[2]],
    })
    resolved = group.get_skus()
    assert resolved.count() == 2
    assert set(resolved.values_list('code', flat=True)) == {'A1', 'G1'}


def test_rule_group_resolves_by_filter(skus):
    group = MasterDataService.create_sku_group({
        'name': 'Acme', 'code': 'GR', 'filter_type': 'rule', 'filter_rules': {'brand': 'Acme'},
    })
    resolved = group.get_skus()
    assert resolved.count() == 2
    assert set(resolved.values_list('code', flat=True)) == {'A1', 'A2'}


def test_rule_group_multi_criteria(skus):
    group = MasterDataService.create_sku_group({
        'name': 'Focus Tools', 'code': 'GFT', 'filter_type': 'rule',
        'filter_rules': {'category': 'Tools', 'is_focus': True},
    })
    assert set(group.get_skus().values_list('code', flat=True)) == {'A1', 'G1'}


# ── API ──────────────────────────────────────────────────────────────────────

def test_api_search_by_brand(admin_client, skus):
    resp = admin_client.get('/api/v1/master/skus/?brand=Globex')
    assert resp.status_code == 200
    assert [s['code'] for s in resp.data['results']] == ['G1']


def test_api_filter_is_focus(admin_client, skus):
    resp = admin_client.get('/api/v1/master/skus/?is_focus=true')
    assert resp.status_code == 200
    assert {s['code'] for s in resp.data['results']} == {'A1', 'G1'}


def test_api_create_sku(admin_client):
    resp = admin_client.post(
        '/api/v1/master/skus/',
        {'code': 'API1', 'name': 'Via API', 'brand': 'Acme'},
        format='json',
    )
    assert resp.status_code == 201
    assert SKU.objects.filter(code='API1').exists()


def test_api_bulk_endpoint(admin_client):
    csv_text = 'code,name,brand\nBULK1,One,Acme\nBULK2,Two,Acme\n'
    resp = admin_client.post('/api/v1/master/skus/bulk/', {'data': csv_text}, format='json')
    assert resp.status_code == 200
    assert resp.data['created'] == 2


def test_api_group_skus_action(admin_client, skus):
    group = MasterDataService.create_sku_group({
        'name': 'Acme', 'code': 'GAPI', 'filter_type': 'rule', 'filter_rules': {'brand': 'Acme'},
    })
    resp = admin_client.get(f'/api/v1/master/sku-groups/{group.id}/skus/')
    assert resp.status_code == 200
    assert {s['code'] for s in resp.data} == {'A1', 'A2'}


def test_api_group_resolved_count_field(admin_client, skus):
    MasterDataService.create_sku_group({
        'name': 'All', 'code': 'GALL', 'filter_type': 'rule', 'filter_rules': {},
    })
    resp = admin_client.get('/api/v1/master/sku-groups/')
    assert resp.status_code == 200
    row = next(g for g in resp.data['results'] if g['code'] == 'GALL')
    assert row['resolved_sku_count'] == SKU.objects.filter(is_active=True).count()


# ── RBAC ─────────────────────────────────────────────────────────────────────

def test_api_requires_master_data_permission(noperm_client):
    assert noperm_client.get('/api/v1/master/skus/').status_code == 403
    assert noperm_client.get('/api/v1/master/sku-groups/').status_code == 403
    assert noperm_client.get('/api/v1/master/uom-conversions/').status_code == 403


# ── Soft delete ──────────────────────────────────────────────────────────────

def test_deactivated_sku_excluded_from_group(skus):
    from apps.master_data.models import SKUGroup
    group = SKUGroup.objects.create(
        code='ACME', name='Acme', filter_type=SKUGroup.FILTER_RULE,
        filter_rules={'brand': 'Acme'},
    )
    assert set(group.get_skus().values_list('code', flat=True)) == {'A1', 'A2'}
    MasterDataService.deactivate_sku(skus[1])  # A2
    assert set(group.get_skus().values_list('code', flat=True)) == {'A1'}


def test_deactivated_sku_excluded_from_explicit_group(skus):
    group = MasterDataService.create_sku_group({
        'name': 'Picks', 'code': 'EP', 'filter_type': 'explicit', 'skus': [skus[0], skus[1]],
    })
    assert group.get_skus().count() == 2
    MasterDataService.deactivate_sku(skus[1])
    assert set(group.get_skus().values_list('code', flat=True)) == {'A1'}


# ── Facets ───────────────────────────────────────────────────────────────────

def test_api_facets(admin_client, skus):
    resp = admin_client.get('/api/v1/master/skus/facets/')
    assert resp.status_code == 200
    assert resp.data['brands'] == ['Acme', 'Globex']
    assert resp.data['categories'] == ['Parts', 'Tools']


# ── Group preview (unsaved) ──────────────────────────────────────────────────

def test_api_preview_rule(admin_client, skus):
    resp = admin_client.post(
        '/api/v1/master/sku-groups/preview/',
        {'filter_type': 'rule', 'filter_rules': {'brand': 'Acme'}},
        format='json',
    )
    assert resp.status_code == 200
    assert resp.data['count'] == 2
    assert {s['code'] for s in resp.data['sample']} == {'A1', 'A2'}


def test_api_preview_explicit(admin_client, skus):
    resp = admin_client.post(
        '/api/v1/master/sku-groups/preview/',
        {'filter_type': 'explicit', 'skus': [skus[0].id]},
        format='json',
    )
    assert resp.status_code == 200
    assert resp.data['count'] == 1


# ── filter_rules validation ──────────────────────────────────────────────────

def test_api_group_rejects_unknown_rule_key(admin_client):
    resp = admin_client.post(
        '/api/v1/master/sku-groups/',
        {'name': 'Bad', 'code': 'BAD', 'filter_type': 'rule',
         'filter_rules': {'bran': 'Acme'}},
        format='json',
    )
    assert resp.status_code == 400
    assert 'Unknown rule field' in str(resp.data)


# ── Bulk import: attributes column ───────────────────────────────────────────

def test_bulk_import_maps_extra_columns_to_attributes(db):
    csv_text = (
        'code,name,brand,pack_size\n'
        'P1,Pack One,Acme,large\n'
    )
    result = MasterDataService.bulk_import_skus(csv_text)
    assert result['status'] == 'success'
    assert SKU.objects.get(code='P1').attributes == {'pack_size': 'large'}


def test_bulk_import_async_dispatch(admin_client):
    """run_async forces the job path → 202 with a bulk job (runs eager in tests)."""
    csv_text = 'code,name\nJ1,One\nJ2,Two\n'
    resp = admin_client.post(
        '/api/v1/master/skus/bulk/',
        {'data': csv_text, 'run_async': True},
        format='json',
    )
    assert resp.status_code == 202
    assert resp.data['job_type'] == 'sku_import'
    assert SKU.objects.filter(code__in=['J1', 'J2']).count() == 2


# ── UOM Conversion API ───────────────────────────────────────────────────────

def test_api_create_uom_conversion(admin_client):
    resp = admin_client.post(
        '/api/v1/master/uom-conversions/',
        {'sku_code': '', 'from_uom': 'case', 'to_uom': 'unit', 'factor': '12'},
        format='json',
    )
    assert resp.status_code == 201
    conv = UOMConversion.objects.get(from_uom='case')
    assert str(conv.factor) == '12.000000'


def test_api_uom_duplicate_rejected(admin_client):
    payload = {'sku_code': 'SKU1', 'from_uom': 'case', 'to_uom': 'unit', 'factor': '24'}
    assert admin_client.post('/api/v1/master/uom-conversions/', payload, format='json').status_code == 201
    assert admin_client.post('/api/v1/master/uom-conversions/', payload, format='json').status_code == 400


def test_deactivated_uom_ignored_by_convert(db):
    from decimal import Decimal
    conv = MasterDataService.create_uom_conversion(
        {'sku_code': '', 'from_uom': 'case', 'to_uom': 'unit', 'factor': Decimal('12')},
    )
    assert MasterDataService.convert_to_base('X', 'case', Decimal('2')) == Decimal('24')
    MasterDataService.deactivate_uom_conversion(conv)
    assert MasterDataService.convert_to_base('X', 'case', Decimal('2')) == Decimal('2')
