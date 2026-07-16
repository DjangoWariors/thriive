"""Structural payout confidentiality — team/subtree payout visibility is impossible.

Three layers under test: role-write rejection, resolve-time clamp, and the
dashboard's payout gating (manager keeps team ranking, never team payouts).
"""
from datetime import date

import pytest

from apps.accounts.models import Role, User, UserRole
from apps.accounts.services import RoleService
from apps.core.exceptions import BusinessError
from apps.core.permissions import highest_level


def _grant(user, perms, code='conf_test'):
    role = Role.objects.create(code=code, name=code, permissions=perms)
    UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return role


# ── layer 1: write-time rejection ────────────────────────────────────────────
@pytest.mark.django_db
def test_role_with_team_final_payout_rejected():
    with pytest.raises(BusinessError, match='payout-confidential'):
        RoleService.create_role({'name': 'Bad', 'code': 'bad',
                                 'permissions': {'final_payout': 'team'}})


@pytest.mark.django_db
def test_role_with_view_edit_report_payout_rejected_on_update():
    role = RoleService.create_role({'name': 'Ok', 'code': 'ok',
                                    'permissions': {'final_payout': 'own_only'}})
    with pytest.raises(BusinessError, match='report_payout'):
        RoleService.update_role(role, {'permissions': {'report_payout': 'view_edit'}})


@pytest.mark.django_db
def test_allowed_confidential_levels_accepted():
    role = RoleService.create_role({'name': 'Fin', 'code': 'fin', 'permissions': {
        'final_payout': 'view_readonly', 'report_payout': 'view_all',
        'achievement_view': 'team',  # non-confidential resources keep the full ladder
    }})
    assert role.pk is not None


# ── layer 2: resolve-time clamp ──────────────────────────────────────────────
@pytest.mark.django_db
def test_force_seeded_team_grant_resolves_to_none():
    user = User.objects.create_user(email='clamp@test.com')
    # Bypass RoleService the way a hand-written seed would.
    _grant(user, {'final_payout': 'team', 'achievement_view': 'team'})
    assert highest_level(user, 'final_payout') == 'none'
    assert highest_level(user, 'achievement_view') == 'team'  # untouched


@pytest.mark.django_db
def test_legal_grant_resolves_normally():
    user = User.objects.create_user(email='own@test.com')
    _grant(user, {'final_payout': 'own_only'})
    assert highest_level(user, 'final_payout') == 'own_only'


# ── layer 3: dashboard gating ────────────────────────────────────────────────
@pytest.mark.django_db
def test_catalog_never_offers_team_for_confidential():
    from apps.accounts.permission_catalog import PERMISSION_CATALOG

    by_code = {r['code']: r for g in PERMISSION_CATALOG for r in g['resources']}
    for code in ('final_payout', 'report_payout'):
        assert 'team' not in by_code[code]['levels']
        assert 'view_edit' not in by_code[code]['levels']
