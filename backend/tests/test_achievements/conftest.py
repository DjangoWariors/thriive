"""Shared fixtures for achievement tests.

Tree:  NSM (root) → ASM (manager) → ASE1, ASE2 (leaves)
Period: June 2026 (Mon Jun 1 → Tue Jun 30); 26 working days excluding Sundays.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.assignments.models import Assignment
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Channel, Node, NodeType, GeographyNode, GeographyType
from apps.kpi_engine.models import KPIDefinition, Transaction
from apps.targets.models import TargetAllocation, TargetPeriod

PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 6, 30)
AS_OF = date(2026, 6, 11)  # 10 working days elapsed of 26


@pytest.fixture
def gt(db):
    return Channel.objects.create(name='General Trade', code='GT')


@pytest.fixture
def ase_type(db):
    return NodeType.objects.create(
        name='ASE', code='ASE', level_order=3, incentive_eligible=True, effective_from=date.today(),
    )


@pytest.fixture
def mgr_type(db):
    return NodeType.objects.create(
        name='ASM', code='ASM', level_order=2, incentive_eligible=True, effective_from=date.today(),
    )


@pytest.fixture
def nsm_type(db):
    return NodeType.objects.create(
        name='NSM', code='NSM', level_order=1, incentive_eligible=True, effective_from=date.today(),
    )


@pytest.fixture
def tree(db, ase_type, mgr_type, nsm_type, gt):
    nsm = Node.objects.create(entity_type=nsm_type, name='NSM', code='NSM', effective_from=date.today())
    asm = Node.objects.create(entity_type=mgr_type, name='ASM', code='ASM', parent=nsm,
                                effective_from=date.today())
    ase1 = Node.objects.create(entity_type=ase_type, name='Deepa', code='ASE1', parent=asm,
                                 channel=gt, effective_from=date.today())
    ase2 = Node.objects.create(entity_type=ase_type, name='Rahul', code='ASE2', parent=asm,
                                 channel=gt, effective_from=date.today())

    # Parallel geography tree (where the work lives): region → area → {town1, town2}.
    # Sales attach to geography; each org entity owns its matching territory via an assignment,
    # so a manager's value rolls up the towns beneath the area/region it owns.
    geo_type = GeographyType.objects.create(name='Sales Geo', code='sales_geo',
                                            levels=['region', 'area', 'town'])
    region = GeographyNode.objects.create(geography_type=geo_type, name='Region', code='REGION', level='region')
    area = GeographyNode.objects.create(geography_type=geo_type, name='Area', code='AREA', level='area', parent=region)
    town1 = GeographyNode.objects.create(geography_type=geo_type, name='Town1', code='TOWN1', level='town', parent=area)
    town2 = GeographyNode.objects.create(geography_type=geo_type, name='Town2', code='TOWN2', level='town', parent=area)
    for entity, node in ((nsm, region), (asm, area), (ase1, town1), (ase2, town2)):
        AssignmentService.create(assignee_id=entity.id, scope_id=node.id, effective_from=date(2025, 1, 1))

    return {'nsm': nsm, 'asm': asm, 'ase1': ase1, 'ase2': ase2,
            'region': region, 'area': area, 'town1': town1, 'town2': town2}


@pytest.fixture
def period(db):
    return TargetPeriod.objects.create(
        name='June 2026', code='JUN26', period_type=TargetPeriod.MONTHLY,
        start_date=PERIOD_START, end_date=PERIOD_END, working_days=20, status=TargetPeriod.PUBLISHED,
    )


@pytest.fixture
def primary_kpi(db):
    return KPIDefinition.objects.create(
        code='PRIMARY', name='Primary Sales', kpi_type=KPIDefinition.VALUE,
        applicable_entity_types=['ASE', 'ASM', 'NSM'], effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum',
                        'net_logic': 'sales_minus_returns'},
    )


def mk_txn(entity_id, **kw):
    """Attribute a transaction to the geography node the org entity owns."""
    a = Assignment.objects.filter(assignee_id=entity_id, role_in_scope='owner', is_active=True).first()
    node_id = a.scope_id if a else entity_id
    defaults = dict(
        transaction_date=date(2026, 6, 5), transaction_type=Transaction.SALE,
        transaction_level=Transaction.SECONDARY, channel_code='GT',
        gross_amount=Decimal('0'), net_amount=Decimal('0'), quantity=Decimal('0'),
    )
    defaults.update(kw)
    return Transaction.objects.create(attributed_node_id=node_id, **defaults)


def mk_alloc(period, kpi, entity, value):
    """Geography-anchored allocation on the territory the entity directly owns — targets are
    geography-canonical, and a person's target is derived from their owned scope."""
    a = Assignment.objects.filter(assignee_id=entity.id, role_in_scope='owner', is_active=True).first()
    return TargetAllocation.objects.create(
        target_period=period, kpi=kpi, geography_node_id=a.scope_id if a else None,
        target_value=Decimal(str(value)), original_target_value=Decimal(str(value)),
    )
