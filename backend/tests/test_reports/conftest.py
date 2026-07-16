from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.assignments.services import AssignmentService
from apps.hierarchy.models import Node, NodeType, GeographyNode, GeographyType

_seq = iter(range(1_000_000))


def make_user(email, *, entity=None, perms=None, superuser=False):
    if superuser:
        return User.objects.create_superuser(email=email, password='pass')
    user = User.objects.create_user(email=email, password='pass', entity=entity)
    if perms:
        code = f'rpt{next(_seq)}'
        role = Role.objects.create(code=code, name=code, permissions=perms)
        UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


def client_for(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


@pytest.fixture
def reports_seeded(db):
    from django.core.management import call_command
    call_command('seed_reports')


@pytest.fixture
def org(db):
    """NSM → ASM → ASE1, ASE2 (with ASM linked to a user for subtree scoping)."""
    et_nsm = NodeType.objects.create(name='NSM', code='NSM', level_order=1,
                                       is_loginable=True, effective_from=date.today())
    et_asm = NodeType.objects.create(name='ASM', code='ASM', level_order=2,
                                       is_loginable=True, effective_from=date.today())
    et_ase = NodeType.objects.create(name='ASE', code='ASE', level_order=3,
                                       effective_from=date.today())
    nsm = Node.objects.create(entity_type=et_nsm, name='Nat Head', code='NSM',
                                effective_from=date.today())
    asm = Node.objects.create(entity_type=et_asm, name='Area Mgr', code='ASM', parent=nsm,
                                effective_from=date.today())
    ase1 = Node.objects.create(entity_type=et_ase, name='Deepa', code='ASE1', parent=asm,
                                 effective_from=date.today())
    ase2 = Node.objects.create(entity_type=et_ase, name='Rahul', code='ASE2', parent=asm,
                                 effective_from=date.today())

    # Geography these people own (sales attach here): region → area → {town1, town2}.
    gt = GeographyType.objects.create(name='Sales Geo', code='sales_geo', levels=['region', 'area', 'town'])
    region = GeographyNode.objects.create(geography_type=gt, name='Region', code='REGION', level='region')
    area = GeographyNode.objects.create(geography_type=gt, name='Area', code='AREA', level='area', parent=region)
    town1 = GeographyNode.objects.create(geography_type=gt, name='Town1', code='TOWN1', level='town', parent=area)
    town2 = GeographyNode.objects.create(geography_type=gt, name='Town2', code='TOWN2', level='town', parent=area)
    for entity, node in ((nsm, region), (asm, area), (ase1, town1), (ase2, town2)):
        AssignmentService.create(assignee_id=entity.id, scope_id=node.id, effective_from=date(2025, 1, 1))

    return {'nsm': nsm, 'asm': asm, 'ase1': ase1, 'ase2': ase2,
            'region': region, 'area': area, 'town1': town1, 'town2': town2}
