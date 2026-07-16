"""Fixtures for workflow tests.

Org tree (entities WITH linked users so hierarchy routing resolves):
    NSM/national head (nsm_user) → ASM/area manager (asm_user) → ASE1, ASE2 (leaves, no user)
"""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.hierarchy.models import Node, NodeType
from apps.incentives.models import PayoutException
from apps.targets.models import TargetPeriod

_seq = iter(range(1_000_000))


def make_user(email, *, entity=None, perms=None, superuser=False):
    if superuser:
        return User.objects.create_superuser(email=email, password='pass')
    user = User.objects.create_user(email=email, password='pass', entity=entity)
    if perms:
        code = f'wfr{next(_seq)}'
        role = Role.objects.create(code=code, name=code, permissions=perms)
        UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


def grant_role(user, role_code, perms=None):
    role, _ = Role.objects.get_or_create(
        code=role_code, defaults={'name': role_code, 'permissions': perms or {}},
    )
    UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return role


def client_for(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


@pytest.fixture
def org(db):
    et_nsm = NodeType.objects.create(name='NSM', code='NSM', level_order=1,
                                       is_loginable=True, effective_from=date.today())
    et_asm = NodeType.objects.create(name='ASM', code='ASM', level_order=2,
                                       is_loginable=True, effective_from=date.today())
    et_ase = NodeType.objects.create(name='ASE', code='ASE', level_order=3,
                                       incentive_eligible=True, effective_from=date.today())
    nsm = Node.objects.create(entity_type=et_nsm, name='Nat Head', code='NSM',
                                effective_from=date.today())
    asm = Node.objects.create(entity_type=et_asm, name='Area Mgr', code='ASM', parent=nsm,
                                effective_from=date.today())
    ase1 = Node.objects.create(entity_type=et_ase, name='Deepa', code='ASE1', parent=asm,
                                 effective_from=date.today())
    ase2 = Node.objects.create(entity_type=et_ase, name='Rahul', code='ASE2', parent=asm,
                                 effective_from=date.today())

    asm_user = make_user('asm@x.com', entity=asm,
                         perms={'exception_management': 'team', 'workflow_management': 'team'})
    nsm_user = make_user('nsm@x.com', entity=nsm,
                         perms={'workflow_management': 'full', 'exception_approve': 'full'})
    grant_role(nsm_user, 'national_head', {'workflow_management': 'full'})

    return {
        'nsm': nsm, 'asm': asm, 'ase1': ase1, 'ase2': ase2,
        'asm_user': asm_user, 'nsm_user': nsm_user,
    }


@pytest.fixture
def period(db):
    return TargetPeriod.objects.create(
        name='June 2026', code='JUN26', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
        working_days=20, status=TargetPeriod.PUBLISHED,
    )


@pytest.fixture
def seeded(db):
    """Seed the standard workflow definitions + FMCG category catalog."""
    from django.core.management import call_command
    call_command('seed_workflows')


def make_exception(entity, period, *, category='medical_leave', actor=None,
                   sales=PayoutException.ACTUAL, scheme=None):
    return PayoutException.objects.create(
        entity=entity, target_period=period, scheme=scheme, category=category,
        sales_kpi_action=sales, reason='test', status=PayoutException.PENDING,
        requested_by=actor,
    )
