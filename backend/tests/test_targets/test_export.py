"""Planning-grid export — the round trip that makes the plan editable in Excel.

The grid serves one level at a time, so the export is the only way to see a whole plan.
Its leading columns are the bulk-import contract: what comes out must go back in unchanged
(``test_export_round_trips``), and it must never hand a scoped user a territory the grid
would have hidden (``test_export_is_territory_scoped``).
"""
import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.assignments.services import AssignmentService
from apps.core.exceptions import BusinessError
from apps.hierarchy.models import GeographyNode, GeographyType, Node, NodeType
from apps.jobs.models import BulkJob
from apps.kpi_engine.models import KPIDefinition
from apps.master_data.models import SKUGroup
from apps.targets.models import PlanKpi, TargetAllocation, TargetPeriod, TargetPlan
from apps.targets.plan_services import PlanService
from apps.targets.services import TargetService

pytestmark = pytest.mark.django_db

BASE = '/api/v1/targets'
_FROM = date(2025, 1, 1)


def _auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return client


def _csv(resp):
    """A streaming CSV response as (header, list-of-dicts)."""
    body = b''.join(resp.streaming_content).decode('utf-8')
    reader = csv.DictReader(io.StringIO(body))
    return body, list(reader)


@pytest.fixture
def world(db):
    gt = GeographyType.objects.create(name='Sales Geo', code='SGEO', levels=['nation', 'zone', 'town'])
    nation = GeographyNode.objects.create(geography_type=gt, name='India', code='IN', level='nation')
    za = GeographyNode.objects.create(geography_type=gt, name='ZoneA', code='ZA', level='zone', parent=nation)
    zb = GeographyNode.objects.create(geography_type=gt, name='ZoneB', code='ZB', level='zone', parent=nation)
    a1 = GeographyNode.objects.create(geography_type=gt, name='A1', code='A1', level='town', parent=za)
    a2 = GeographyNode.objects.create(geography_type=gt, name='A2', code='A2', level='town', parent=za)

    etype = NodeType.objects.create(name='Role', code='ROLE', level_order=1, effective_from=date.today())
    zoa = Node.objects.create(entity_type=etype, name='ZOA', code='ZOA', effective_from=date.today())
    AssignmentService.create(assignee_id=zoa.id, scope_id=za.id, effective_from=_FROM)

    role = Role.objects.create(code='tgt_full', name='full', permissions={'target_management': 'full'})
    admin = User.objects.create_user(email='admin@x.com', password='pass')
    UserRole.objects.create(user=admin, role=role, effective_from=date.today())
    zoa_user = User.objects.create_user(email='zoa@x.com', password='pass', entity=zoa)
    UserRole.objects.create(user=zoa_user, role=role, effective_from=date.today())

    kpi = KPIDefinition.objects.create(
        code='CORE_VALUE', name='Core Value', kpi_type=KPIDefinition.VALUE, effective_from=date.today(),
        measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'},
    )
    period = TargetPeriod.objects.create(
        code='FY27-M06', name='Jun 2026', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )
    plan = TargetPlan.objects.create(
        name='FY27 AOP', code='AOP-FY27', period=period, root_geography=nation,
        status=TargetPlan.PUBLISHED,
    )
    PlanKpi.objects.create(plan=plan, kpi=kpi, top_value=Decimal('10000'))
    for node, value in ((nation, '10000'), (za, '6000'), (zb, '4000'), (a1, '2500'), (a2, '3500')):
        TargetAllocation.objects.create(
            target_period=period, plan=plan, kpi=kpi, geography_node=node,
            target_value=Decimal(value), original_target_value=Decimal(value),
            status=TargetAllocation.APPROVED)
    return {'nation': nation, 'za': za, 'zb': zb, 'a1': a1, 'a2': a2,
            'admin': admin, 'zoa_user': zoa_user, 'kpi': kpi, 'period': period, 'plan': plan}


def test_export_streams_the_whole_subtree(world):
    """Every level under the root, not the one level the grid serves — including the
    product-split rows the grid never shows."""
    group = SKUGroup.objects.create(name='Focus', code='FOCUS')
    TargetAllocation.objects.create(
        target_period=world['period'], plan=world['plan'], kpi=world['kpi'],
        geography_node=world['a1'], sku_group=group,
        target_value=Decimal('900'), original_target_value=Decimal('900'))

    resp = _auth(world['admin']).get(f"{BASE}/plans/{world['plan'].id}/export/")
    assert resp.status_code == 200
    assert resp['Content-Disposition'] == 'attachment; filename="plan-AOP-FY27-targets.csv"'

    body, rows = _csv(resp)
    assert body.startswith('period_code,kpi_code,geography_node_code,channel_code,sku_group_code,target_value')
    assert len(rows) == 6  # nation + 2 zones + 2 towns + 1 product row
    assert {r['geography_node_code'] for r in rows} == {'IN', 'ZA', 'ZB', 'A1', 'A2'}
    assert {r['level'] for r in rows} == {'nation', 'zone', 'town'}
    product = next(r for r in rows if r['sku_group_code'] == 'FOCUS')
    assert product['geography_node_code'] == 'A1' and Decimal(product['target_value']) == Decimal('900')


def test_export_names_the_accountable_owner_per_row(world):
    """Zone A's owner is assigned to ZA only, but is accountable for its towns too — the
    file must say so, matching the grid's Owner column. Zone B is vacant."""
    _, rows = _csv(_auth(world['admin']).get(f"{BASE}/plans/{world['plan'].id}/export/"))
    by_code = {r['geography_node_code']: r for r in rows}

    assert by_code['ZA']['owner_code'] == 'ZOA' and by_code['ZA']['owner_name'] == 'ZOA'
    assert by_code['A1']['owner_code'] == 'ZOA'  # inherited from the zone
    assert by_code['A2']['owner_code'] == 'ZOA'
    assert by_code['ZB']['owner_code'] == '' and by_code['ZB']['owner_name'] == ''  # vacant
    assert by_code['IN']['owner_code'] == ''     # above the assignment, not below it


def test_export_owner_prefers_the_direct_assignment(world):
    """A town with its own owner reports that person, not the zone's."""
    etype = NodeType.objects.get(code='ROLE')
    tso = Node.objects.create(entity_type=etype, name='TSO A1', code='TSO1',
                              effective_from=date.today())
    AssignmentService.create(assignee_id=tso.id, scope_id=world['a1'].id, effective_from=_FROM)

    _, rows = _csv(_auth(world['admin']).get(f"{BASE}/plans/{world['plan'].id}/export/"))
    by_code = {r['geography_node_code']: r for r in rows}
    assert by_code['A1']['owner_code'] == 'TSO1'
    assert by_code['A2']['owner_code'] == 'ZOA'  # sibling still inherits


def test_export_reports_the_effective_target(world):
    """An override is the number on screen, so it must be the number in the file."""
    alloc = TargetAllocation.objects.get(geography_node=world['a1'], sku_group=None)
    alloc.override_value = Decimal('2800')
    alloc.save(update_fields=['override_value'])

    _, rows = _csv(_auth(world['admin']).get(f"{BASE}/plans/{world['plan'].id}/export/"))
    a1 = next(r for r in rows if r['geography_node_code'] == 'A1')
    assert Decimal(a1['target_value']) == Decimal('2800')
    assert Decimal(a1['original_target_value']) == Decimal('2500')


def test_export_is_territory_scoped(world):
    """Zone A's owner exports their own subtree — never Zone B, whose numbers the grid
    would not have shown them either."""
    _, rows = _csv(_auth(world['zoa_user']).get(f"{BASE}/plans/{world['plan'].id}/export/"))
    codes = {r['geography_node_code'] for r in rows}
    assert codes == {'ZA', 'A1', 'A2'}
    assert 'ZB' not in codes and 'IN' not in codes


def test_export_honours_the_parent_and_kpi_filters(world):
    other = KPIDefinition.objects.create(
        code='EC', name='Effective Coverage', kpi_type=KPIDefinition.VALUE,
        effective_from=date.today(), measure_config={'measure_field': 'net_amount', 'aggregation': 'sum'})
    TargetAllocation.objects.create(
        target_period=world['period'], plan=world['plan'], kpi=other, geography_node=world['za'],
        target_value=Decimal('50'), original_target_value=Decimal('50'))
    admin = _auth(world['admin'])

    # parent scopes the subtree; kpi picks one of the plan's KPIs.
    _, subtree = _csv(admin.get(f"{BASE}/plans/{world['plan'].id}/export/",
                                {'parent': world['za'].id, 'kpi': world['kpi'].id}))
    assert {r['geography_node_code'] for r in subtree} == {'ZA', 'A1', 'A2'}
    assert {r['kpi_code'] for r in subtree} == {'CORE_VALUE'}


def test_import_template_carries_the_plans_real_codes(world):
    """The importer resolves everything by code, so a template with invented codes would
    teach the wrong ones. Every sample row must resolve against this plan."""
    resp = _auth(world['admin']).get(f"{BASE}/plans/{world['plan'].id}/import-template/")
    assert resp.status_code == 200
    assert resp['Content-Disposition'] == 'attachment; filename="plan-AOP-FY27-import-template.csv"'

    rows = list(csv.DictReader(io.StringIO(resp.content.decode('utf-8'))))
    assert rows, 'template must carry sample rows'
    assert set(rows[0]) == {'period_code', 'kpi_code', 'geography_node_code',
                            'channel_code', 'sku_group_code', 'target_value'}
    assert {r['period_code'] for r in rows} == {'FY27-M06'}
    assert {r['kpi_code'] for r in rows} == {'CORE_VALUE'}
    # Deepest territories first — the level a planner actually fills in.
    assert {r['geography_node_code'] for r in rows} == {'A1', 'A2'}


def test_import_template_is_not_uploadable_until_filled_in(world):
    """A blank target is a gap in the file, not a target of zero — uploading the template
    as-is must fail loudly rather than write zeros over a plan."""
    resp = _auth(world['admin']).get(f"{BASE}/plans/{world['plan'].id}/import-template/")
    before = dict(TargetAllocation.objects.values_list('id', 'target_value'))

    result = TargetService.bulk_import_allocations(resp.content.decode('utf-8'))
    assert result['status'] == 'validation_failed'
    assert 'target_value is required' in result['errors'][0]['errors'][0]
    assert dict(TargetAllocation.objects.values_list('id', 'target_value')) == before


def test_import_template_is_territory_scoped(world):
    """A reviewer's template offers territories they actually own."""
    resp = _auth(world['zoa_user']).get(f"{BASE}/plans/{world['plan'].id}/import-template/")
    rows = list(csv.DictReader(io.StringIO(resp.content.decode('utf-8'))))
    assert {r['geography_node_code'] for r in rows} <= {'ZA', 'A1', 'A2'}


def test_oversized_upload_is_refused_before_anything_runs(world):
    """A governed import is row-by-row (~90 rows/s on the update path), so an unbounded file
    would hold targets locked for tens of minutes. It must be refused up front — with the
    plan run named as the way to set a whole tree — not accepted and left to grind."""
    header = ','.join(PlanService.IMPORT_FIELDS) + '\n'
    oversized = header + ''.join(
        f"{world['period'].code},{world['kpi'].code},NODE{i},,,{i}\n"
        for i in range(TargetService._MAX_IMPORT_ROWS + 1))
    before = TargetAllocation.objects.count()

    with pytest.raises(BusinessError) as exc:
        TargetService.bulk_import_allocations(oversized)
    assert '10,001 rows' in str(exc.value) and 'capped at 10,000' in str(exc.value)
    assert 'plan run' in str(exc.value)
    assert TargetAllocation.objects.count() == before

    # And the API refuses it without queueing a job for the user to watch fail.
    resp = _auth(world['admin']).post(f'{BASE}/allocations/bulk/', {'data': oversized},
                                      format='json')
    assert resp.status_code == 422
    assert BulkJob.objects.count() == 0


def test_export_round_trips_through_the_importer(world):
    """The whole point: export → (edit) → re-import. Untouched rows are a no-op; an edited
    row goes through the governed path and keeps its change-cap anchor."""
    body, rows = _csv(_auth(world['admin']).get(f"{BASE}/plans/{world['plan'].id}/export/"))

    # Re-uploading the file byte-for-byte changes nothing.
    result = TargetService.bulk_import_allocations(body, actor=world['admin'])
    assert result['status'] == 'success'
    assert result['unchanged'] == len(rows) and result['updated'] == 0 and result['created'] == 0

    # Edit one cell the way a planner would in Excel, then upload again.
    edited = body.replace('ZA,,,6000.0000', 'ZA,,,6600.0000')
    assert edited != body
    result = TargetService.bulk_import_allocations(edited, actor=world['admin'], reason='Q1 push')
    assert result['updated'] == 1 and result['unchanged'] == len(rows) - 1

    za = TargetAllocation.objects.get(geography_node=world['za'], sku_group=None)
    assert za.effective_target == Decimal('6600')
    assert za.original_target_value == Decimal('6000')      # the cap anchor survives the upload
    assert za.status == TargetAllocation.PENDING            # published plan → needs a checker
    revision = za.revisions.get()
    assert revision.reason == 'Q1 push' and revision.new_value == Decimal('6600')
