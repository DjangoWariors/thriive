"""
9 tests for RBACPermission covering every clause in the spec.
"""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.accounts.models import Role, User, UserRole
from apps.core.permissions import RBACPermission, highest_level, subtree_lookup
from apps.hierarchy.models import Node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _View:
    """Minimal view double with a required_permission attribute."""
    required_permission = 'test_resource'


def _make_request(rf, method='GET', user=None):
    req = getattr(rf, method.lower())('/')
    req.user = user
    return req


def _make_user_role(user, role, *, effective_to=None):
    return UserRole.objects.create(
        user=user,
        role=role,
        effective_from=date.today(),
        effective_to=effective_to,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user(db):
    return User.objects.create_user(email='rep@example.com', password='pass')


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(email='admin@example.com', password='pass')


@pytest.fixture
def role_full(db):
    return Role.objects.create(
        name='Full Access', code='full_access',
        permissions={'test_resource': 'full'},
    )


@pytest.fixture
def role_own(db):
    return Role.objects.create(
        name='Own Only', code='own_only_role',
        permissions={'test_resource': 'own_only'},
    )


@pytest.fixture
def role_team(db):
    return Role.objects.create(
        name='Team', code='team_role',
        permissions={'test_resource': 'team'},
    )


@pytest.fixture
def role_no_perm(db):
    return Role.objects.create(
        name='No Perm', code='no_perm_role',
        permissions={},
    )


@pytest.fixture
def role_view_all(db):
    return Role.objects.create(
        name='View All', code='view_all_role',
        permissions={'test_resource': 'view_all'},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRBACPermission:

    def test_superuser_bypass(self, rf, superuser):
        """Superuser skips every check — always allowed."""
        req = _make_request(rf, user=superuser)
        perm = RBACPermission()
        assert perm.has_permission(req, _View()) is True
        assert perm.has_object_permission(req, _View(), object()) is True

    def test_deny_unauthenticated(self, rf):
        """Anonymous user is always denied."""
        from django.contrib.auth.models import AnonymousUser
        req = _make_request(rf, user=AnonymousUser())
        assert RBACPermission().has_permission(req, _View()) is False

    def test_check_json_perms_allowed(self, rf, user, role_full):
        """User whose role grants the required permission is allowed."""
        _make_user_role(user, role_full)
        req = _make_request(rf, user=user)
        assert RBACPermission().has_permission(req, _View()) is True

    def test_check_json_perms_denied(self, rf, user, role_no_perm):
        """User whose role has no entry for this permission is denied."""
        _make_user_role(user, role_no_perm)
        req = _make_request(rf, user=user)
        assert RBACPermission().has_permission(req, _View()) is False

    def test_own_only_entity_match_allowed(self, rf, user, role_own):
        """own_only: user.entity.pk == obj.entity_id → allowed."""
        _make_user_role(user, role_own)
        entity = Node.objects.create(name='mgr_entity', effective_from=date.today())
        user.entity = entity
        req = _make_request(rf, user=user)
        obj = SimpleNamespace(entity_id=entity.pk)
        assert RBACPermission().has_object_permission(req, _View(), obj) is True

    def test_own_only_entity_no_match_denied(self, rf, user, role_own):
        """own_only: user.entity.pk != obj.entity_id → denied."""
        _make_user_role(user, role_own)
        entity = Node.objects.create(name='mgr_entity', effective_from=date.today())
        user.entity = entity
        req = _make_request(rf, user=user)
        obj = SimpleNamespace(entity_id=entity.pk + 9999)
        assert RBACPermission().has_object_permission(req, _View(), obj) is False

    def test_team_via_path_prefix(self, rf, user, role_team):
        """
        team: Node.objects.filter(path__startswith=user.entity.path) → allowed.
        Only the hierarchy.Node lookup is mocked; accounts.UserRole uses real DB.
        """
        _make_user_role(user, role_team)
        entity = Node.objects.create(name='mgr_entity', effective_from=date.today())
        entity.path = '/NSM/RSM/'   # Python attribute; no DB column until Step 2.1
        user.entity = entity
        req = _make_request(rf, user=user)
        obj = SimpleNamespace(entity_id=10)

        from django.apps import apps as django_apps
        # Capture the real get_model before the patch replaces it
        _real = django_apps.get_model

        mock_entity_cls = MagicMock()
        mock_entity_cls.objects.filter.return_value.exists.return_value = True

        def _side_effect(app_label, model_name=None):
            if app_label == 'hierarchy':
                return mock_entity_cls
            return _real(app_label, model_name) if model_name else _real(app_label)

        with patch('apps.core.permissions.apps.get_model', side_effect=_side_effect):
            result = RBACPermission().has_object_permission(req, _View(), obj)

        assert result is True
        mock_entity_cls.objects.filter.assert_called_once_with(
            pk=10, path__startswith='/NSM/RSM/', is_current=True,
        )

    def test_expired_role_ignored(self, rf, user, role_full):
        """A UserRole whose effective_to is in the past is not counted."""
        yesterday = date.today() - timedelta(days=1)
        _make_user_role(user, role_full, effective_to=yesterday)
        req = _make_request(rf, user=user)
        assert RBACPermission().has_permission(req, _View()) is False

    def test_multiple_roles_highest_wins(self, rf, user, role_no_perm, role_full):
        """When a user has several roles the highest permission level is used."""
        _make_user_role(user, role_no_perm)
        _make_user_role(user, role_full)
        req = _make_request(rf, user=user)
        assert RBACPermission().has_permission(req, _View()) is True

    def test_view_all_reads_any_object(self, rf, user, role_view_all):
        """view_all may read any object (no entity match needed)."""
        _make_user_role(user, role_view_all)
        req = _make_request(rf, method='GET', user=user)
        assert RBACPermission().has_object_permission(req, _View(), object()) is True

    def test_view_all_cannot_write(self, rf, user, role_view_all):
        """view_all is read-only — writes are denied at the object layer."""
        _make_user_role(user, role_view_all)
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            req = _make_request(rf, method=method, user=user)
            assert RBACPermission().has_object_permission(req, _View(), object()) is False, method

    def test_deactivated_role_ignored(self, rf, user, role_full):
        """A role that is itself deactivated grants nothing."""
        _make_user_role(user, role_full)
        role_full.is_active = False
        role_full.save(update_fields=['is_active'])
        assert highest_level(user, 'test_resource') == 'none'

    def test_highest_level_memoized_per_user(self, django_assert_num_queries, user, role_full):
        """Resolving the same permission twice on one user instance hits the DB once."""
        _make_user_role(user, role_full)
        with django_assert_num_queries(1):
            assert highest_level(user, 'test_resource') == 'full'
            assert highest_level(user, 'test_resource') == 'full'


def test_subtree_lookup_kwargs():
    """The shared subtree rule builds a path-prefix lookup on the given field."""
    assert subtree_lookup('/A/B/') == {'path__startswith': '/A/B/'}
    assert subtree_lookup('/A/B/', 'entity__path') == {'entity__path__startswith': '/A/B/'}
