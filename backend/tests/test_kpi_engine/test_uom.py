"""UOM normalization — volume KPIs sum across mixed packs via a base unit."""
from datetime import date
from decimal import Decimal

import pytest

from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Node, NodeType, GeographyNode, GeographyType
from apps.kpi_engine.calculator import KPICalculator
from apps.kpi_engine.models import KPIDefinition
from apps.kpi_engine.services import KPIService
from apps.master_data.models import UOMConversion
from apps.master_data.services import MasterDataService

PERIOD = (date(2026, 6, 1), date(2026, 6, 30))

CSV = (
    'attributed_node_id,transaction_date,sku_code,quantity,uom,net_amount\n'
    '{node},2026-06-01,SKU1,2,case,1000\n'   # 2 cases × 24 = 48 units
    '{node},2026-06-02,SKU1,6,unit,300\n'    # 6 units
)


@pytest.fixture
def entity(db):
    et = NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())
    e = Node.objects.create(entity_type=et, name='ASE', code='ASE1', effective_from=date.today())
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['town'])
    node = GeographyNode.objects.create(geography_type=gt, name='Town', code='TOWN1', level='town')
    AssignmentService.create(assignee_id=e.id, scope_id=node.id, effective_from=date(2025, 1, 1))
    e._node_id = node.id
    return e


def test_convert_to_base_prefers_sku_specific(db):
    UOMConversion.objects.create(sku_code='', from_uom='case', to_uom='unit', factor=Decimal('12'))
    UOMConversion.objects.create(sku_code='SKU1', from_uom='case', to_uom='unit', factor=Decimal('24'))
    assert MasterDataService.convert_to_base('SKU1', 'case', Decimal('2')) == Decimal('48')
    assert MasterDataService.convert_to_base('OTHER', 'case', Decimal('2')) == Decimal('24')  # global
    assert MasterDataService.convert_to_base('X', 'unit', Decimal('5')) == Decimal('5')  # no rule → passthrough


def test_volume_kpi_sums_base_quantity(entity):
    UOMConversion.objects.create(sku_code='SKU1', from_uom='case', to_uom='unit', factor=Decimal('24'))
    KPIService.bulk_import_transactions(CSV.format(node=entity._node_id))
    kpi = KPIDefinition.objects.create(
        code='VOL', name='Volume (units)', kpi_type=KPIDefinition.VALUE, decimal_places=2, effective_from=date.today(),
        measure_config={'measure_field': 'base_quantity', 'aggregation': 'sum', 'net_logic': 'all'},
    )
    # 48 (2 cases) + 6 units = 54.00 units; raw quantity would have wrongly read 8.
    assert KPICalculator(kpi, *PERIOD).compute_for_entity(entity.id) == Decimal('54.00')
