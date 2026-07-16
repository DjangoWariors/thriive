"""Sprint 12 hardening: auth throttling + nightly achievement scheduling.

Throttling is disabled in dev/test settings, so the throttle test enables a low
rate by setting it directly on DRF's api_settings and restoring it in a finally
(override_settings(REST_FRAMEWORK=...) does not reliably revert under pytest,
which would leak the low rate into the rest of the suite). The global
``_clear_throttle_cache`` fixture (tests/conftest.py) clears history per test.
"""
import datetime
from unittest.mock import patch

import pytest
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.targets.models import TargetPeriod

LOGIN_URL = '/api/v1/auth/login/'


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email='rep@example.com', password='correct_pass',
        first_name='Deepa', last_name='Sharma',
    )


@pytest.mark.django_db
def test_auth_endpoint_throttles_after_rate(client, user):
    body = {'identifier': 'rep@example.com', 'password': 'correct_pass'}
    # The throttle reads its rates from the (class-level) THROTTLE_RATES dict, so
    # mutate that exact object in place and restore it — this is fully reversible
    # and cannot leak the low rate into the rest of the suite.
    rates = SimpleRateThrottle.THROTTLE_RATES
    saved = dict(rates)
    rates.update({'auth': '2/min', 'otp': '2/min', 'bulk': '2/hour'})
    try:
        assert client.post(LOGIN_URL, body, format='json').status_code == 200
        assert client.post(LOGIN_URL, body, format='json').status_code == 200
        # Third request within the window exceeds auth scope (2/min) → 429.
        assert client.post(LOGIN_URL, body, format='json').status_code == 429
    finally:
        rates.clear()
        rates.update(saved)


def test_auth_views_declare_throttle_scopes():
    from apps.accounts.views import OTPRequestView, OTPVerifyView, PasswordLoginView

    assert PasswordLoginView.throttle_scope == 'auth'
    assert OTPVerifyView.throttle_scope == 'auth'
    assert OTPRequestView.throttle_scope == 'otp'


@pytest.mark.django_db
def test_run_scheduled_achievements_targets_only_live_periods():
    """The nightly task dispatches one compute job per period that is in an
    auto-status AND whose date range covers today — nothing else."""
    from apps.achievements.tasks import run_scheduled_achievements

    today = datetime.date.today()
    span = datetime.timedelta(days=15)

    live = TargetPeriod.objects.create(
        name='Live', code='LIVE', start_date=today - span, end_date=today + span,
        status=TargetPeriod.PUBLISHED,
    )
    TargetPeriod.objects.create(  # right status, wrong dates (already ended)
        name='Past', code='PAST', start_date=today - 2 * span, end_date=today - span,
        status=TargetPeriod.PUBLISHED,
    )
    TargetPeriod.objects.create(  # covers today, but draft → excluded by default statuses
        name='Draft', code='DRAFT', start_date=today - span, end_date=today + span,
        status=TargetPeriod.DRAFT,
    )

    with patch('apps.jobs.dispatch.run_or_dispatch') as dispatch:
        result = run_scheduled_achievements()

    assert result['periods'] == 1
    assert result['dispatched'][0]['period_id'] == live.id
    assert dispatch.call_count == 1


@pytest.mark.django_db
def test_run_scheduled_achievements_includes_draft_period_with_live_plan():
    """Governance is keyed to PLAN status: a published plan must feed the nightly
    compute even while its period is still draft on the planning calendar —
    guards the 'published July targets but dashboard stays empty' regression."""
    from apps.achievements.tasks import run_scheduled_achievements
    from apps.hierarchy.models import GeographyNode, GeographyType
    from apps.targets.models import TargetPlan

    today = datetime.date.today()
    span = datetime.timedelta(days=15)

    planned = TargetPeriod.objects.create(
        name='Planned', code='PLANNED', start_date=today - span, end_date=today + span,
        status=TargetPeriod.DRAFT,
    )
    TargetPeriod.objects.create(  # draft, covers today, no live plan → still excluded
        name='Bare', code='BARE', start_date=today - span, end_date=today + span,
        status=TargetPeriod.DRAFT,
    )
    geo_type = GeographyType.objects.create(name='G', code='g', levels=['nation'])
    root = GeographyNode.objects.create(geography_type=geo_type, name='Nation', code='NATION', level='nation')
    TargetPlan.objects.create(
        name='AOP', code='AOP', period=planned, root_geography=root, status=TargetPlan.PUBLISHED,
    )

    with patch('apps.jobs.dispatch.run_or_dispatch') as dispatch:
        result = run_scheduled_achievements()

    assert result['periods'] == 1
    assert result['dispatched'][0]['period_id'] == planned.id
    assert dispatch.call_count == 1


@pytest.mark.django_db
def test_run_scheduled_achievements_honours_configurable_statuses(settings):
    settings.THRIIVE_ACHIEVEMENT_AUTO_STATUSES = ['locked']
    from apps.achievements.tasks import run_scheduled_achievements

    today = datetime.date.today()
    span = datetime.timedelta(days=10)
    TargetPeriod.objects.create(
        name='Published', code='PUB', start_date=today - span, end_date=today + span,
        status=TargetPeriod.PUBLISHED,
    )
    locked = TargetPeriod.objects.create(
        name='Locked', code='LOCK', start_date=today - span, end_date=today + span,
        status=TargetPeriod.LOCKED,
    )

    with patch('apps.jobs.dispatch.run_or_dispatch') as dispatch:
        result = run_scheduled_achievements()

    # Only 'locked' is in the configured auto-statuses now.
    assert result['periods'] == 1
    assert result['dispatched'][0]['period_id'] == locked.id
    assert dispatch.call_count == 1
