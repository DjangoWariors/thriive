"""
GeographyNodeService.bulk_import — territory bulk import (CSV/JSON).
"""
from datetime import date

import pytest

from apps.accounts.models import User
from apps.core.exceptions import BusinessError
from apps.hierarchy.config_services import GeographyNodeService
from apps.hierarchy.models import GeographyNode, GeographyType


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(email='admin@example.com', password='adminpass')


@pytest.fixture
def geo_type(db):
    return GeographyType.objects.create(
        name='Sales Geography', code='sales_geo',
        levels=['nation', 'town', 'outlet'],
    )


@pytest.fixture
def india(db, geo_type):
    return GeographyNode.objects.create(
        geography_type=geo_type, name='India', code='INDIA', level='nation',
    )


CSV_HEADER = 'geography_type_code,name,code,parent_code,level,attributes_json\n'


@pytest.mark.django_db
def test_import_creates_nodes_with_in_batch_parents(geo_type, india, admin_user):
    # Outlet row listed BEFORE its town parent — topological sort must handle it.
    csv_text = CSV_HEADER + (
        'sales_geo,Outlet 1,OUT1,TOWN1,outlet,\n'
        'sales_geo,Town 1,TOWN1,INDIA,town,\n'
        'sales_geo,Outlet 2,OUT2,TOWN1,outlet,"{""outlet_count"": 1}"\n'
    )
    result = GeographyNodeService.bulk_import(csv_text, fmt='csv', user=admin_user)
    assert result == {'status': 'success', 'created': 3}

    town = GeographyNode.objects.get(code='TOWN1')
    out1 = GeographyNode.objects.get(code='OUT1')
    assert town.parent.code == 'INDIA'
    assert out1.parent_id == town.pk
    assert out1.path.startswith(town.path)
    assert GeographyNode.objects.get(code='OUT2').attributes == {'outlet_count': 1}


@pytest.mark.django_db
def test_any_row_error_rolls_back_everything(geo_type, india, admin_user):
    csv_text = CSV_HEADER + (
        'sales_geo,Town 1,TOWN1,INDIA,town,\n'
        'sales_geo,Bad Level,BAD1,INDIA,galaxy,\n'
    )
    result = GeographyNodeService.bulk_import(csv_text, fmt='csv', user=admin_user)
    assert result['status'] == 'validation_failed'
    assert result['errors'][0]['row'] == 2
    assert not GeographyNode.objects.filter(code='TOWN1').exists()


@pytest.mark.django_db
def test_duplicate_and_existing_codes_rejected(geo_type, india, admin_user):
    csv_text = CSV_HEADER + (
        'sales_geo,India Again,INDIA,,nation,\n'
        'sales_geo,Town 1,TOWN1,INDIA,town,\n'
        'sales_geo,Town 1 Again,TOWN1,INDIA,town,\n'
    )
    result = GeographyNodeService.bulk_import(csv_text, fmt='csv', user=admin_user)
    assert result['status'] == 'validation_failed'
    rows_in_error = {e['row'] for e in result['errors']}
    assert rows_in_error == {1, 3}


@pytest.mark.django_db
def test_parent_must_be_shallower_level(geo_type, india, admin_user):
    csv_text = CSV_HEADER + (
        'sales_geo,Town 1,TOWN1,INDIA,town,\n'
        'sales_geo,Town 2,TOWN2,TOWN1,town,\n'
    )
    result = GeographyNodeService.bulk_import(csv_text, fmt='csv', user=admin_user)
    assert result['status'] == 'validation_failed'
    assert 'below its parent' in result['errors'][0]['errors'][0]


@pytest.mark.django_db
def test_unknown_type_and_parent_reported(geo_type, admin_user):
    csv_text = CSV_HEADER + (
        'nope_geo,Town 1,TOWN1,,town,\n'
        'sales_geo,Town 2,TOWN2,MISSING,town,\n'
    )
    result = GeographyNodeService.bulk_import(csv_text, fmt='csv', user=admin_user)
    assert result['status'] == 'validation_failed'
    assert "geography_type_code 'nope_geo' not found" in result['errors'][0]['errors'][0]
    assert "parent_code 'MISSING' not found" in str(result['errors'][1]['errors'])


@pytest.mark.django_db
def test_dry_run_creates_nothing(geo_type, india, admin_user):
    csv_text = CSV_HEADER + 'sales_geo,Town 1,TOWN1,INDIA,town,\n'
    result = GeographyNodeService.bulk_import(csv_text, fmt='csv', user=admin_user, dry_run=True)
    assert result['status'] == 'valid'
    assert result['would_create'] == 1
    assert not GeographyNode.objects.filter(code='TOWN1').exists()


@pytest.mark.django_db
def test_json_format_supported(geo_type, india, admin_user):
    rows = [{
        'geography_type_code': 'sales_geo', 'name': 'Town 1',
        'code': 'TOWN1', 'parent_code': 'INDIA', 'level': 'town',
    }]
    result = GeographyNodeService.bulk_import(rows, fmt='json', user=admin_user)
    assert result == {'status': 'success', 'created': 1}


@pytest.mark.django_db
def test_bad_format_raises(geo_type, admin_user):
    with pytest.raises(BusinessError):
        GeographyNodeService.bulk_import('x', fmt='xml', user=admin_user)
