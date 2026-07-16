"""Shared fixtures/helpers for notification tests.

Tiny org: ASM (manager, loginable) → ASE (leaf). The ASM has a linked User so it can be
resolved as the 'checker' above the ASE.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.hierarchy.models import Node, NodeType
from apps.targets.models import TargetPeriod


def client_for(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


@pytest.fixture
def period(db):
    return TargetPeriod.objects.create(
        name='June 2026', code='JUN26', period_type=TargetPeriod.MONTHLY,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
        working_days=20, status=TargetPeriod.PUBLISHED,
    )


@pytest.fixture
def org(db):
    asm_type = NodeType.objects.create(
        name='ASM', code='ASM', level_order=1, incentive_eligible=True, is_loginable=True,
        effective_from=date.today(),
    )
    ase_type = NodeType.objects.create(
        name='ASE', code='ASE', level_order=2, incentive_eligible=True,
        effective_from=date.today(),
    )
    asm = Node.objects.create(entity_type=asm_type, name='ASM', code='ASM',
                                effective_from=date.today())
    ase = Node.objects.create(entity_type=ase_type, name='Deepa', code='ASE1', parent=asm,
                                effective_from=date.today())
    asm_user = User.objects.create_user(email='asm@x.com', password='pass', entity=asm)
    requester = User.objects.create_user(email='maker@x.com', password='pass')
    return {'asm': asm, 'ase': ase, 'asm_user': asm_user, 'requester': requester}
