"""External metric catalog + ingestion + calculator — exact Decimal assertions.

Two trees (same shape as test_calculator):
  Organisation:  ASM1 ─ owns ─▶ REGION;  ASE1 ─ owns ─▶ TOWN1;  ASE2 ─ owns ─▶ TOWN2
  Geography:     REGION ─┬─ TOWN1
                         └─ TOWN2

Territory-grain metrics (TLSD) attach to geography nodes and roll up the owned
subtree; person-grain metrics (iQuest, RCPA) attach to the org entity and never
roll up. Period under test is June 2026.
"""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User, UserRole
from apps.accounts.services import ApiKeyService
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.kpi_engine.calculator import KPICalculator
from apps.kpi_engine.models import (
    ExternalMetric,
    ExternalMetricValue,
    IntegrationBatch,
    KPIDefinition,
)
from apps.kpi_engine.services import ExternalMetricService, IngestionService, KPIService

PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 6, 30)
_FROM = date(2025, 1, 1)


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture
def etype(db):
    return NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())


@pytest.fixture
def geo(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['region', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='Region', code='REGION', level='region')
    town1 = GeographyNode.objects.create(geography_type=gt, name='Town1', code='TOWN1', level='town', parent=region)
    town2 = GeographyNode.objects.create(geography_type=gt, name='Town2', code='TOWN2', level='town', parent=region)
    return {'region': region, 'town1': town1, 'town2': town2}


def _own(entity, node):
    AssignmentService.create(assignee_id=entity.id, scope_id=node.id, effective_from=_FROM)


@pytest.fixture
def manager(db, etype, geo):
    m = Node.objects.create(entity_type=etype, name='ASM', code='ASM1', effective_from=date.today())
    _own(m, geo['region'])
    return m


@pytest.fixture
def ase1(db, etype, manager, geo):
    e = Node.objects.create(entity_type=etype, name='ASE1', code='ASE1', parent=manager, effective_from=date.today())
    _own(e, geo['town1'])
    return e


@pytest.fixture
def ase2(db, etype, manager, geo):
    e = Node.objects.create(entity_type=etype, name='ASE2', code='ASE2', parent=manager, effective_from=date.today())
    _own(e, geo['town2'])
    return e


@pytest.fixture
def tlsd(db):
    """Territory-grain daily count metric."""
    return ExternalMetric.objects.create(
        code='TLSD', name='Total Lines Sold per Day', granularity=ExternalMetric.GEOGRAPHY_NODE,
        period_grain=ExternalMetric.DAILY, default_aggregation=ExternalMetric.SUM, decimal_places=0,
    )


@pytest.fixture
def iquest(db):
    """Person-grain monthly score metric."""
    return ExternalMetric.objects.create(
        code='IQUEST_SCORE', name='iQuest Score', granularity=ExternalMetric.ENTITY,
        period_grain=ExternalMetric.MONTHLY, default_aggregation=ExternalMetric.LATEST, unit='%',
    )


def _mv(metric, *, entity=None, node=None, on, value, source='', ref=''):
    return ExternalMetricValue.objects.create(
        metric=metric, entity=entity, node_id=node.id if node else None,
        measured_on=on, value=Decimal(str(value)), source=source, external_ref=ref,
    )


def _external_kpi(metric_code, *, aggregation=None, dp=2, **cfg_extra):
    cfg = {'metric_code': metric_code, 'target_source': 'allocation'}
    if aggregation:
        cfg['aggregation'] = aggregation
    cfg.update(cfg_extra)
    return KPIDefinition(
        code=f'K_{metric_code}', name=metric_code, kpi_type=KPIDefinition.EXTERNAL,
        external_config=cfg, decimal_places=dp, effective_from=date.today(),
    )


# ── calculator ───────────────────────────────────────────────────────────────
def test_node_grain_sums_and_rolls_up_owned_subtree(tlsd, geo, manager, ase1, ase2):
    _mv(tlsd, node=geo['town1'], on=date(2026, 6, 3), value='12')
    _mv(tlsd, node=geo['town1'], on=date(2026, 6, 4), value='8')
    _mv(tlsd, node=geo['town2'], on=date(2026, 6, 3), value='5')
    _mv(tlsd, node=geo['town2'], on=date(2026, 5, 30), value='99')  # outside window

    calc = KPICalculator(_external_kpi('TLSD', dp=0), PERIOD_START, PERIOD_END)
    assert calc.compute_for_entity(ase1.id) == Decimal('20')
    assert calc.compute_for_entity(ase2.id) == Decimal('5')
    assert calc.compute_for_entity(manager.id) == Decimal('25')  # region subtree


def test_entity_grain_reads_exact_entity_no_rollup(iquest, manager, ase1, ase2):
    _mv(iquest, entity=ase1, on=date(2026, 6, 1), value='82.50')
    _mv(iquest, entity=ase2, on=date(2026, 6, 1), value='91.00')

    calc = KPICalculator(_external_kpi('IQUEST_SCORE', aggregation='latest'), PERIOD_START, PERIOD_END)
    assert calc.compute_for_entity(ase1.id) == Decimal('82.50')
    assert calc.compute_for_entity(ase2.id) == Decimal('91.00')
    # A manager has no personal score — never an average of the team's.
    assert calc.compute_for_entity(manager.id) == Decimal('0.00')


def test_avg_and_latest_aggregations(iquest, ase1):
    metric = ExternalMetric.objects.create(
        code='RCPA_PCT', name='RCPA %', granularity=ExternalMetric.ENTITY,
        period_grain=ExternalMetric.DAILY, default_aggregation=ExternalMetric.AVG,
    )
    _mv(metric, entity=ase1, on=date(2026, 6, 2), value='80')
    _mv(metric, entity=ase1, on=date(2026, 6, 9), value='90')

    avg = KPICalculator(_external_kpi('RCPA_PCT', aggregation='avg'), PERIOD_START, PERIOD_END)
    assert avg.compute_for_entity(ase1.id) == Decimal('85.00')
    latest = KPICalculator(_external_kpi('RCPA_PCT', aggregation='latest'), PERIOD_START, PERIOD_END)
    assert latest.compute_for_entity(ase1.id) == Decimal('90.00')


def test_entity_grain_is_zero_on_geography_axis(iquest, geo, ase1):
    _mv(iquest, entity=ase1, on=date(2026, 6, 1), value='82.50')
    calc = KPICalculator(_external_kpi('IQUEST_SCORE'), PERIOD_START, PERIOD_END)
    # Geography-axis bulk (disaggregation path) must not misread node ids as entities.
    assert calc.compute_bulk_for_nodes([geo['town1'].id]) == {geo['town1'].id: Decimal('0.00')}


# ── config validation ────────────────────────────────────────────────────────
def test_external_kpi_requires_known_metric(db):
    errors = KPIService.validate_kpi_config({
        'code': 'X', 'kpi_type': KPIDefinition.EXTERNAL,
        'external_config': {'metric_code': 'NOPE'},
    })
    assert any('unknown metric' in e for e in errors)


def test_external_kpi_fixed_target_must_be_positive(tlsd):
    errors = KPIService.validate_kpi_config({
        'code': 'X', 'kpi_type': KPIDefinition.EXTERNAL,
        'external_config': {'metric_code': 'TLSD', 'target_source': 'fixed', 'fixed_target': 0},
    })
    assert any('fixed_target' in e for e in errors)


def test_metric_grain_frozen_once_values_exist(tlsd, geo):
    _mv(tlsd, node=geo['town1'], on=date(2026, 6, 3), value='1')
    from apps.core.exceptions import BusinessError
    with pytest.raises(BusinessError, match='once values exist'):
        ExternalMetricService.update(tlsd, {'granularity': ExternalMetric.ENTITY})


def test_metric_in_use_cannot_be_deactivated(tlsd):
    KPIService.create_kpi({
        'code': 'K_TLSD', 'name': 'TLSD', 'kpi_type': KPIDefinition.EXTERNAL,
        'external_config': {'metric_code': 'TLSD'},
    })
    from apps.core.exceptions import BusinessError
    with pytest.raises(BusinessError, match='referenced by KPI'):
        ExternalMetricService.deactivate(tlsd)


# ── ingestion (service) ──────────────────────────────────────────────────────
def test_push_partial_accept_with_per_row_errors(tlsd, iquest, geo, ase1):
    rows = [
        {'metric_code': 'TLSD', 'node_id': geo['town1'].id, 'measured_on': '2026-06-03', 'value': '12', 'external_ref': 'r1'},
        {'metric_code': 'NOPE', 'node_id': geo['town1'].id, 'measured_on': '2026-06-03', 'value': '1'},
        {'metric_code': 'TLSD', 'entity_id': ase1.id, 'measured_on': '2026-06-03', 'value': '1'},  # wrong grain
        {'metric_code': 'IQUEST_SCORE', 'entity_id': ase1.id, 'measured_on': '2026-06-15', 'value': '85', 'external_ref': 'r4'},
    ]
    result = IngestionService.push_metric_values(source='sfa_sync', rows=rows)

    assert result['status'] == IntegrationBatch.PARTIAL
    assert (result['received'], result['accepted'], result['rejected']) == (4, 2, 2)
    assert [e['index'] for e in result['errors']] == [1, 2]
    # Monthly grain normalises to month start.
    iq = ExternalMetricValue.objects.get(metric=iquest)
    assert iq.measured_on == date(2026, 6, 1)
    batch = IntegrationBatch.objects.get(pk=result['batch_id'])
    assert batch.row_errors[0]['row']['metric_code'] == 'NOPE'  # full payload kept for re-push


def test_push_is_idempotent_on_source_ref(tlsd, geo):
    rows = [{'metric_code': 'TLSD', 'node_id': geo['town1'].id, 'measured_on': '2026-06-03',
             'value': '12', 'external_ref': 'r1'}]
    r1 = IngestionService.push_metric_values(source='sfa_sync', rows=rows)
    rows[0]['value'] = '15'
    r2 = IngestionService.push_metric_values(source='sfa_sync', rows=rows)

    assert r1['created'] == 1 and r2['updated'] == 1
    assert ExternalMetricValue.objects.count() == 1
    assert ExternalMetricValue.objects.get().value == Decimal('15.0000')


def test_push_upserts_on_natural_key_without_ref(iquest, ase1):
    rows = [{'metric_code': 'IQUEST_SCORE', 'entity_id': ase1.id, 'measured_on': '2026-06-15', 'value': '80'}]
    IngestionService.push_metric_values(source='sfa_sync', rows=rows)
    rows[0]['value'] = '88'
    IngestionService.push_metric_values(source='sfa_sync', rows=rows)

    assert ExternalMetricValue.objects.count() == 1
    assert ExternalMetricValue.objects.get().value == Decimal('88.0000')


def test_duplicate_client_batch_ref_replays_original(tlsd, geo):
    rows = [{'metric_code': 'TLSD', 'node_id': geo['town1'].id, 'measured_on': '2026-06-03',
             'value': '12', 'external_ref': 'r1'}]
    r1 = IngestionService.push_metric_values(source='sfa_sync', rows=rows, client_batch_ref='B-001')
    r2 = IngestionService.push_metric_values(source='sfa_sync', rows=rows, client_batch_ref='B-001')

    assert r2['replayed'] is True
    assert r2['batch_id'] == r1['batch_id']
    assert IntegrationBatch.objects.count() == 1


# ── push endpoint (API + RBAC) ───────────────────────────────────────────────
def _integration_client(db):
    svc = User.objects.create_user(email='sfa-bot@test.com')
    role = Role.objects.create(code='integration', name='Integration',
                               permissions={'integration_push': 'full'})
    UserRole.objects.create(user=svc, role=role, effective_from=date.today())
    _, plaintext = ApiKeyService.issue('SFA', svc)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=plaintext)
    return client


def test_push_endpoint_with_api_key(db, tlsd, geo):
    client = _integration_client(db)
    resp = client.post('/api/v1/kpis/metric-values/push/', {
        'source': 'sfa_sync', 'client_batch_ref': 'B-1',
        'rows': [{'metric_code': 'TLSD', 'node_id': geo['town1'].id,
                  'measured_on': '2026-06-03', 'value': '12', 'external_ref': 'r1'}],
    }, format='json')
    assert resp.status_code == 200
    assert resp.data['accepted'] == 1
    assert IntegrationBatch.objects.get().pushed_by.email == 'sfa-bot@test.com'


def test_push_endpoint_requires_integration_push(db, tlsd, geo):
    svc = User.objects.create_user(email='nobody@test.com')
    _, plaintext = ApiKeyService.issue('SFA', svc)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=plaintext)
    resp = client.post('/api/v1/kpis/metric-values/push/', {
        'source': 'sfa_sync', 'rows': [{'metric_code': 'TLSD'}],
    }, format='json')
    assert resp.status_code == 403


def test_push_endpoint_rejects_anonymous(db):
    resp = APIClient().post('/api/v1/kpis/metric-values/push/', {
        'source': 'sfa_sync', 'rows': [{'metric_code': 'TLSD'}],
    }, format='json')
    assert resp.status_code == 401


# ── CSV bulk import ──────────────────────────────────────────────────────────
def test_csv_import_all_or_nothing(tlsd, geo):
    good = (
        'metric_code,node_id,measured_on,value\n'
        f'TLSD,{geo["town1"].id},2026-06-03,12\n'
        f'TLSD,{geo["town2"].id},2026-06-03,5\n'
    )
    result = IngestionService.bulk_import_metric_values(good)
    assert result == {'status': 'success', 'created': 2, 'updated': 0, 'errors': []}

    bad = good + 'NOPE,1,2026-06-03,1\n'
    result = IngestionService.bulk_import_metric_values(bad)
    assert result['status'] == 'validation_failed'
    assert result['errors'][0]['row'] == 4
    assert ExternalMetricValue.objects.count() == 2  # nothing extra written
