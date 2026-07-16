"""Geography-canonical allocation invariants + geography attribute validation."""
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.hierarchy.models import GeographyNode, GeographyType
from apps.hierarchy.services import GeographyService
from apps.kpi_engine.models import KPIDefinition
from apps.targets.models import TargetAllocation, TargetPeriod


@pytest.fixture
def geo_type(db):
    return GeographyType.objects.create(
        name='Sales Geo', code='SGEO', levels=['country', 'state'],
        attribute_schema=[{'key': 'outlet_count', 'label': 'Outlets', 'type': 'integer', 'required': False}],
    )


@pytest.fixture
def country(db, geo_type):
    return GeographyNode.objects.create(geography_type=geo_type, name='India', code='IN', level='country')


@pytest.fixture
def kpi(db):
    return KPIDefinition.objects.create(
        code='K', name='Secondary NSV', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum', 'net_logic': 'sales_minus_returns'},
    )


@pytest.fixture
def period(db):
    return TargetPeriod.objects.create(
        code='P1', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), status=TargetPeriod.DRAFT,
    )


# ── allocation is geography-anchored ─────────────────────────────────────────
def test_allocation_is_geography_anchored(period, kpi, country):
    a = TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=country,
        target_value=Decimal('10000'), original_target_value=Decimal('10000'),
    )
    assert a.geography_node_id == country.id
    assert a.effective_target == Decimal('10000')


def test_allocation_dimensions_are_unique(period, kpi, country):
    TargetAllocation.objects.create(target_period=period, kpi=kpi, geography_node=country, target_value=1)
    with pytest.raises(IntegrityError):
        TargetAllocation.objects.create(target_period=period, kpi=kpi, geography_node=country, target_value=2)


def test_override_wins_over_target_value(period, kpi, country):
    a = TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node=country,
        target_value=Decimal('10000'), override_value=Decimal('12000'),
    )
    assert a.effective_target == Decimal('12000')


# ── geography attribute validation ────────────────────────────────────────────
def test_geo_attribute_validation_rejects_bad_type(geo_type):
    errors = GeographyService.validate_attributes(geo_type, {'outlet_count': 'not-a-number'})
    assert errors and 'Outlets' in errors[0]


def test_geo_attribute_validation_passes(geo_type):
    assert GeographyService.validate_attributes(geo_type, {'outlet_count': 500}) == []
