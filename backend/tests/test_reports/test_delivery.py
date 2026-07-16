"""Data-lake export — delivery targets (S3/SFTP push) + the dataset pull API."""
from datetime import date
from decimal import Decimal
from unittest import mock

import pytest

from apps.reports.delivery import DeliveryError, push_to_target
from apps.reports.models import DeliveryTarget, ReportDefinition, ReportExecution, ReportSchedule
from apps.reports.schedule_service import ReportScheduleService

from .conftest import client_for, make_user


@pytest.fixture
def s3_target(db):
    return DeliveryTarget.objects.create(
        code='LAKE', name='Client data lake', kind=DeliveryTarget.S3,
        config={'bucket': 'client-lake', 'prefix': 'thriive/extracts',
                'region': 'ap-south-1', 'access_key_id': 'AKIA_TEST'},
        credential_env='THRIIVE_LAKE_SECRET',
    )


@pytest.fixture
def sftp_target(db):
    return DeliveryTarget.objects.create(
        code='CLIENT_SFTP', name='Client SFTP', kind=DeliveryTarget.SFTP,
        config={'host': 'sftp.example.com', 'port': 2222, 'path': '/inbound', 'username': 'thriive'},
        credential_env='THRIIVE_SFTP_SECRET',
    )


# ── push_to_target ────────────────────────────────────────────────────────────
def test_s3_push(monkeypatch, s3_target):
    monkeypatch.setenv('THRIIVE_LAKE_SECRET', 'shh')
    fake_client = mock.MagicMock()
    with mock.patch('boto3.client', return_value=fake_client) as client_factory:
        written = push_to_target(s3_target, 'x.csv', b'a,b\n1,2\n')

    client_factory.assert_called_once_with(
        's3', region_name='ap-south-1',
        aws_access_key_id='AKIA_TEST', aws_secret_access_key='shh',
    )
    fake_client.put_object.assert_called_once_with(
        Bucket='client-lake', Key='thriive/extracts/x.csv', Body=b'a,b\n1,2\n',
    )
    assert written == 's3://client-lake/thriive/extracts/x.csv'


def test_sftp_push(monkeypatch, sftp_target):
    monkeypatch.setenv('THRIIVE_SFTP_SECRET', 'shh')
    fake_sftp = mock.MagicMock()
    fake_transport = mock.MagicMock()
    with mock.patch('paramiko.Transport', return_value=fake_transport), \
         mock.patch('paramiko.SFTPClient.from_transport', return_value=fake_sftp):
        written = push_to_target(sftp_target, 'x.csv', b'data')

    fake_transport.connect.assert_called_once_with(username='thriive', password='shh')
    assert fake_sftp.putfo.call_args[0][1] == '/inbound/x.csv'
    assert written == '/inbound/x.csv'


def test_missing_credential_env_raises(s3_target, monkeypatch):
    monkeypatch.delenv('THRIIVE_LAKE_SECRET', raising=False)
    with pytest.raises(DeliveryError, match='THRIIVE_LAKE_SECRET'):
        push_to_target(s3_target, 'x.csv', b'')


# ── target schedule run ───────────────────────────────────────────────────────
@pytest.mark.django_db
def test_target_schedule_generates_once_and_pushes(monkeypatch, reports_seeded, s3_target):
    monkeypatch.setenv('THRIIVE_LAKE_SECRET', 'shh')
    owner = make_user('lake-owner@test.com', perms={'report_sales': 'view_all',
                                                    'report_schedule': 'full'})
    definition = ReportDefinition.objects.get(code='secondary_sales_register')
    schedule = ReportSchedule.objects.create(
        definition=definition, name='Nightly lake extract', format='csv',
        delivery=ReportSchedule.Delivery.TARGET, delivery_target=s3_target, owner=owner,
    )

    fake_client = mock.MagicMock()
    with mock.patch('boto3.client', return_value=fake_client):
        result = ReportScheduleService.run(schedule)

    assert result == {'recipients': 1, 'delivered': 1}
    execution = ReportExecution.objects.get(definition=definition)
    assert execution.status == ReportExecution.Status.COMPLETED
    assert execution.delivered_at is not None and execution.delivery_error == ''
    assert fake_client.put_object.call_count == 1


@pytest.mark.django_db
def test_target_schedule_records_delivery_failure(monkeypatch, reports_seeded, sftp_target):
    monkeypatch.delenv('THRIIVE_SFTP_SECRET', raising=False)  # missing secret → failure
    owner = make_user('sftp-owner@test.com', perms={'report_sales': 'view_all'})
    definition = ReportDefinition.objects.get(code='secondary_sales_register')
    schedule = ReportSchedule.objects.create(
        definition=definition, name='Broken extract', format='csv',
        delivery=ReportSchedule.Delivery.TARGET, delivery_target=sftp_target, owner=owner,
    )
    result = ReportScheduleService.run(schedule)
    assert result['delivered'] == 0
    execution = ReportExecution.objects.get(definition=definition)
    assert 'THRIIVE_SFTP_SECRET' in execution.delivery_error
    assert execution.delivered_at is None


# ── dataset pull API ──────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_dataset_returns_same_rows_paginated(reports_seeded, org):
    from apps.kpi_engine.models import Transaction

    for i in range(5):
        Transaction.objects.create(
            attributed_node_id=org['town1'].id, transaction_date=date(2026, 6, 5),
            net_amount=Decimal('100.00'), sku_code=f'SKU{i}', channel_code='GT',
            transaction_level=Transaction.SECONDARY,
        )
    user = make_user('lake-puller@test.com', perms={'report_sales': 'view_all'})
    client = client_for(user)

    resp = client.get('/api/v1/reports/datasets/secondary_sales_register/?page=1&page_size=3')
    assert resp.status_code == 200
    assert resp.data['count'] == 5
    assert len(resp.data['results']) == 3
    assert resp.data['has_next'] is True

    resp2 = client.get('/api/v1/reports/datasets/secondary_sales_register/?page=2&page_size=3')
    assert len(resp2.data['results']) == 2
    assert resp2.data['has_next'] is False


@pytest.mark.django_db
def test_dataset_permission_enforced(reports_seeded):
    nobody = make_user('nobody@test.com', perms={'dashboard': 'own_only'})
    resp = client_for(nobody).get('/api/v1/reports/datasets/secondary_sales_register/')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_non_dataset_report_is_404(reports_seeded):
    user = make_user('u404@test.com', perms={'report_sales': 'view_all'})
    resp = client_for(user).get('/api/v1/reports/datasets/channel_mix/')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_payout_dataset_access_logged(reports_seeded):
    from apps.audit.models import AccessLog

    finance = make_user('finance-lake@test.com', perms={'report_payout': 'view_readonly'})
    resp = client_for(finance).get(
        '/api/v1/reports/datasets/payout_register/', {'period': '1'},
    )
    assert resp.status_code == 200
    assert AccessLog.objects.filter(resource='payout_register', action='export').exists()
