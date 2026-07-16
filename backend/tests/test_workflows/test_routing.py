import pytest

from apps.workflows.routing import manager_at_level, managers_up, role_holders_above

pytestmark = pytest.mark.django_db


def test_manager_at_level_returns_direct_loginable_manager(org):
    res = manager_at_level(org['ase1'], 1)
    assert [u.email for u in res] == ['asm@x.com']


def test_manager_skips_non_loginable_levels(org):
    # ASE1's parent ASM has a user; level 2 reaches NSM's user.
    res = manager_at_level(org['ase1'], 2)
    assert [u.email for u in res] == ['nsm@x.com']


def test_managers_up_lists_nearest_first(org):
    res = managers_up(org['ase1'], 5)
    assert [u.email for u in res] == ['asm@x.com', 'nsm@x.com']


def test_role_holders_above_resolves_in_subtree(org):
    res = role_holders_above('national_head', org['ase1'])
    assert org['nsm_user'] in res


def test_role_holders_above_falls_back_when_none_in_tree(org, db):
    # area_manager role held by nobody above → empty above → fall back to all holders.
    from tests.test_workflows.conftest import grant_role, make_user
    standalone = make_user('standalone@x.com')
    grant_role(standalone, 'finance', {'workflow_management': 'full'})
    res = role_holders_above('finance', org['ase1'])
    assert standalone in res
