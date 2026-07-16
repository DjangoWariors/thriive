"""Transaction JSON push — partial accept, idempotency, batch-ref replay, auth."""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User, UserRole
from apps.accounts.services import ApiKeyService
from apps.hierarchy.models import GeographyNode, GeographyType
from apps.kpi_engine.models import IntegrationBatch, Transaction
from apps.kpi_engine.services import IngestionService


@pytest.fixture
def node(db):
    gt = GeographyType.objects.create(name='Geo', code='geo', levels=['town'])
    return GeographyNode.objects.create(geography_type=gt, name='Town', code='TOWN', level='town')


def _row(node, ref, **kw):
    row = {
        'attributed_node_id': node.id, 'transaction_date': '2026-06-05',
        'net_amount': '1000.00', 'gross_amount': '1100.00', 'quantity': '2',
        'sku_code': 'SKU1', 'channel_code': 'GT', 'external_ref': ref,
    }
    row.update(kw)
    return row


def test_partial_accept_with_per_row_errors(node):
    rows = [
        _row(node, 'r1'),
        _row(node, 'r2', attributed_node_id=999999),        # unknown node
        _row(node, ''),                                     # missing external_ref
        _row(node, 'r4', transaction_date='bogus'),         # bad date
        _row(node, 'r5'),
    ]
    result = IngestionService.push_transactions(source='sfa_sync', rows=rows)

    assert (result['received'], result['accepted'], result['rejected']) == (5, 2, 3)
    assert result['status'] == IntegrationBatch.PARTIAL
    assert [e['index'] for e in result['errors']] == [1, 2, 3]
    assert Transaction.objects.count() == 2


def test_repush_updates_in_place_no_duplicates(node):
    rows = [_row(node, 'r1')]
    r1 = IngestionService.push_transactions(source='dms_sync', rows=rows)
    rows[0]['net_amount'] = '2500.00'
    r2 = IngestionService.push_transactions(source='dms_sync', rows=rows)

    assert r1['created'] == 1 and r2['updated'] == 1
    assert Transaction.objects.count() == 1
    assert Transaction.objects.get().net_amount == Decimal('2500.00')


def test_duplicate_client_batch_ref_replays(node):
    rows = [_row(node, 'r1')]
    r1 = IngestionService.push_transactions(source='dms_sync', rows=rows, client_batch_ref='B-9')
    r2 = IngestionService.push_transactions(source='dms_sync', rows=rows, client_batch_ref='B-9')
    assert r2['replayed'] is True and r2['batch_id'] == r1['batch_id']
    assert IntegrationBatch.objects.count() == 1


def test_base_quantity_computed(node):
    IngestionService.push_transactions(source='api_push', rows=[_row(node, 'r1', quantity='3')])
    txn = Transaction.objects.get()
    assert txn.base_quantity == Decimal('3.0000')  # no UOM conversion configured → 1:1


def test_invalid_source_rejected_per_row(node):
    result = IngestionService.push_transactions(
        source='api_push', rows=[_row(node, 'r1', source='qr_scan')],
    )
    assert result['rejected'] == 1
    assert 'source' in result['errors'][0]['errors'][0]


# ── endpoint auth ─────────────────────────────────────────────────────────────
def _client(*, with_permission: bool):
    svc = User.objects.create_user(email=f'bot-{with_permission}@test.com')
    if with_permission:
        role = Role.objects.create(code=f'int_{with_permission}', name='Integration',
                                   permissions={'integration_push': 'full'})
        UserRole.objects.create(user=svc, role=role, effective_from=date.today())
    _, plaintext = ApiKeyService.issue('DMS', svc)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=plaintext)
    return client


def test_push_endpoint_with_api_key(db, node):
    resp = _client(with_permission=True).post('/api/v1/kpis/transactions/push/', {
        'source': 'dms_sync', 'client_batch_ref': 'B-1', 'rows': [_row(node, 'r1')],
    }, format='json')
    assert resp.status_code == 200
    assert resp.data['accepted'] == 1


def test_push_endpoint_requires_permission(db, node):
    resp = _client(with_permission=False).post('/api/v1/kpis/transactions/push/', {
        'source': 'dms_sync', 'rows': [_row(node, 'r1')],
    }, format='json')
    assert resp.status_code == 403


def test_push_endpoint_rejects_anonymous(db):
    resp = APIClient().post('/api/v1/kpis/transactions/push/', {
        'source': 'dms_sync', 'rows': [{}],
    }, format='json')
    assert resp.status_code == 401
