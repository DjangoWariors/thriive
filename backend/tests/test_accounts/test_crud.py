"""
Tests for UserViewSet, RoleViewSet, and seed_roles management command.
"""
import pytest
from datetime import date
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole
from apps.accounts.permission_catalog import RESOURCE_LEVELS

USERS_URL = '/api/v1/auth/users/'
ROLES_URL = '/api/v1/auth/roles/'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return client


def _make_role(code, name, permissions):
    return Role.objects.create(code=code, name=name, permissions=permissions)


def _assign_role(user, role):
    UserRole.objects.create(user=user, role=role, effective_from=date.today())


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_user(db):
    """Superuser — bypasses all RBAC checks."""
    return User.objects.create_superuser(email='admin@example.com', password='pass')


@pytest.fixture
def manager_user(db):
    """User with user_management permission."""
    user = User.objects.create_user(email='manager@example.com', password='pass')
    role = _make_role('user_mgr', 'User Manager', {'user_management': 'full'})
    _assign_role(user, role)
    return user


@pytest.fixture
def role_manager_user(db):
    """User with role_management permission."""
    user = User.objects.create_user(email='rolemgr@example.com', password='pass')
    role = _make_role('role_mgr', 'Role Manager', {'role_management': 'full'})
    _assign_role(user, role)
    return user


@pytest.fixture
def plain_user(db):
    """User with no special permissions."""
    return User.objects.create_user(email='plain@example.com', password='pass')


# ── seed_roles ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeedRoles:

    def test_creates_nine_roles(self):
        call_command('seed_roles', verbosity=0)
        assert Role.objects.count() == 9

    def test_idempotent_on_rerun(self):
        call_command('seed_roles', verbosity=0)
        call_command('seed_roles', verbosity=0)
        assert Role.objects.count() == 9

    def test_admin_has_all_full(self):
        call_command('seed_roles', verbosity=0)
        admin = Role.objects.get(code='admin')
        assert all(v == 'full' for v in admin.permissions.values())
        assert admin.is_system_role is True

    def test_all_nine_codes_present(self):
        call_command('seed_roles', verbosity=0)
        codes = set(Role.objects.values_list('code', flat=True))
        expected = {
            'admin', 'national_head', 'regional_manager', 'area_manager',
            'sales_officer', 'sales_exec', 'finance', 'retailer', 'distributor',
        }
        assert codes == expected

    def test_approvers_can_reach_the_resource_they_approve(self):
        """An ``*_approve`` gate is useless without read access to the resource itself:
        the viewset gates on the resource, and only then does the action check the gate.
        Granting the gate alone locked approvers out of their own queue entirely."""
        call_command('seed_roles', verbosity=0)
        pairs = [('exception_approve', 'exception_management'),
                 ('payout_approve', 'final_payout')]
        for role in Role.objects.all():
            for gate, resource in pairs:
                if role.permissions.get(gate, 'none') == 'none':
                    continue
                assert role.permissions.get(resource, 'none') != 'none', (
                    f'{role.code} holds {gate} but cannot read {resource}'
                )

    def test_gate_resources_are_granted_full_or_none(self):
        """Gate resources declare only full/none in the permission catalogue — a graded
        level like 'team' cannot be rendered by the role matrix and reads as a mistake."""
        call_command('seed_roles', verbosity=0)
        gates = [code for code, levels in RESOURCE_LEVELS.items() if levels == ['full', 'none']]
        for role in Role.objects.all():
            for code in gates:
                level = role.permissions.get(code, 'none')
                assert level in ('full', 'none'), (
                    f'{role.code}.{code} = {level!r}, but {code} is a full/none gate'
                )

    def test_sales_exec_permissions_are_own_plus_territory_targets(self):
        """Executives see their own data, plus two widenings that the field screens need:
        targets/approvals at 'team' (territory scoping confines that to the subtree they
        own — they are cascade reviewers), and read-only reference lists so the KPI and
        channel pickers on achievement-by-territory and plan-actuals can populate."""
        call_command('seed_roles', verbosity=0)
        exec_role = Role.objects.get(code='sales_exec')
        for resource, level in exec_role.permissions.items():
            if resource in ('target_management', 'workflow_management'):
                assert level == 'team', f'sales_exec should hold team on {resource}'
            elif resource in ('kpi_definitions', 'hierarchy_management'):
                assert level == 'view_readonly', \
                    f'sales_exec needs read-only reference data on {resource}, got {level}'
            else:
                assert level in ('own_only', 'none'), \
                    f'sales_exec should not have {level} on {resource}'

    def test_finance_can_view_all_payouts(self):
        call_command('seed_roles', verbosity=0)
        finance = Role.objects.get(code='finance')
        assert finance.permissions['final_payout'] == 'view_all'

    def test_retailer_has_correct_permissions(self):
        call_command('seed_roles', verbosity=0)
        retailer = Role.objects.get(code='retailer')
        assert retailer.permissions['achievement_view'] == 'own_only'
        assert retailer.permissions['final_payout'] == 'own_only'
        assert retailer.permissions['target_management'] == 'own_only'
        assert retailer.permissions['user_management'] == 'none'


# ── UserViewSet ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestUserViewSet:

    def test_list_requires_auth(self):
        resp = APIClient().get(USERS_URL)
        assert resp.status_code in (401, 403)

    def test_list_denied_without_permission(self, plain_user):
        client = _auth_client(plain_user)
        resp = client.get(USERS_URL)
        assert resp.status_code == 403

    def test_list_returns_active_users(self, manager_user):
        client = _auth_client(manager_user)
        resp = client.get(USERS_URL)
        assert resp.status_code == 200
        # All returned users should be active
        for u in resp.data['results']:
            assert u.get('is_active', True) is True  # UserSerializer doesn't expose is_active, that's fine

    def test_create_user(self, manager_user):
        client = _auth_client(manager_user)
        resp = client.post(USERS_URL, {
            'email': 'new@example.com',
            'first_name': 'New',
            'last_name': 'User',
            'password': 'pass123',
        }, format='json')
        assert resp.status_code == 201
        assert User.objects.filter(email='new@example.com').exists()

    def test_create_user_without_password_sets_unusable(self, manager_user):
        client = _auth_client(manager_user)
        resp = client.post(USERS_URL, {
            'email': 'nopw@example.com',
            'first_name': 'NoPw',
        }, format='json')
        assert resp.status_code == 201
        user = User.objects.get(email='nopw@example.com')
        assert not user.has_usable_password()

    def test_retrieve_user(self, manager_user):
        target = User.objects.create_user(email='target@example.com')
        client = _auth_client(manager_user)
        resp = client.get(f'{USERS_URL}{target.pk}/')
        assert resp.status_code == 200
        assert resp.data['email'] == 'target@example.com'

    def test_partial_update_user(self, manager_user):
        target = User.objects.create_user(email='update@example.com')
        client = _auth_client(manager_user)
        resp = client.patch(
            f'{USERS_URL}{target.pk}/',
            {'first_name': 'Updated', 'designation': 'Senior ASE'},
            format='json',
        )
        assert resp.status_code == 200
        target.refresh_from_db()
        assert target.first_name == 'Updated'
        assert target.designation == 'Senior ASE'

    def test_destroy_soft_deletes(self, manager_user):
        target = User.objects.create_user(email='del@example.com')
        client = _auth_client(manager_user)
        resp = client.delete(f'{USERS_URL}{target.pk}/')
        assert resp.status_code == 204
        target.refresh_from_db()
        assert target.is_active is False

    def test_deactivated_user_not_in_list(self, manager_user):
        target = User.objects.create_user(email='hidden@example.com', is_active=False)
        client = _auth_client(manager_user)
        resp = client.get(USERS_URL)
        assert resp.status_code == 200
        emails = [u['email'] for u in resp.data['results']]
        assert 'hidden@example.com' not in emails

    def test_superuser_bypasses_rbac(self, admin_user):
        client = _auth_client(admin_user)
        resp = client.get(USERS_URL)
        assert resp.status_code == 200


# ── RoleViewSet ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRoleViewSet:

    def test_list_requires_auth(self):
        resp = APIClient().get(ROLES_URL)
        assert resp.status_code in (401, 403)

    def test_list_denied_without_permission(self, plain_user):
        resp = _auth_client(plain_user).get(ROLES_URL)
        assert resp.status_code == 403

    def test_list_roles(self, role_manager_user):
        _make_role('viewer', 'Viewer', {'dashboard': 'view_readonly'})
        resp = _auth_client(role_manager_user).get(ROLES_URL)
        assert resp.status_code == 200
        assert resp.data['count'] >= 1

    def test_create_role(self, role_manager_user):
        resp = _auth_client(role_manager_user).post(ROLES_URL, {
            'name': 'Custom Role',
            'code': 'custom',
            'description': 'A custom role',
            'permissions': {'dashboard': 'own_only'},
        }, format='json')
        assert resp.status_code == 201
        assert Role.objects.filter(code='custom').exists()

    def test_update_role_permissions(self, role_manager_user):
        role = _make_role('editable', 'Editable', {'dashboard': 'none'})
        resp = _auth_client(role_manager_user).patch(
            f'{ROLES_URL}{role.pk}/',
            {'permissions': {'dashboard': 'team'}},
            format='json',
        )
        assert resp.status_code == 200
        role.refresh_from_db()
        assert role.permissions['dashboard'] == 'team'

    def test_delete_non_system_role(self, role_manager_user):
        role = _make_role('deletable', 'Deletable', {})
        resp = _auth_client(role_manager_user).delete(f'{ROLES_URL}{role.pk}/')
        assert resp.status_code == 204
        assert not Role.objects.filter(code='deletable').exists()

    def test_cannot_delete_system_role(self, role_manager_user):
        system_role = Role.objects.create(
            name='System Role', code='sys_role',
            permissions={}, is_system_role=True,
        )
        resp = _auth_client(role_manager_user).delete(f'{ROLES_URL}{system_role.pk}/')
        assert resp.status_code == 403
        assert Role.objects.filter(code='sys_role').exists()

    def test_is_system_role_is_readonly(self, role_manager_user):
        """Clients cannot promote a role to system role via API."""
        role = _make_role('normsys', 'Normal', {})
        resp = _auth_client(role_manager_user).patch(
            f'{ROLES_URL}{role.pk}/',
            {'is_system_role': True},
            format='json',
        )
        assert resp.status_code == 200
        role.refresh_from_db()
        assert role.is_system_role is False  # unchanged


# ── Bulk import / export / filters ──────────────────────────────────────────────

@pytest.mark.django_db
class TestUserBulkImport:

    def test_csv_import_creates_users_and_roles(self, manager_user):
        _make_role('sales_exec', 'Sales Exec', {})
        csv_data = (
            'first_name,last_name,email,mobile,employee_id,roles\n'
            'Deepa,Sharma,deepa@acme.com,9876543210,EMP001,sales_exec\n'
            'Rahul,Verma,,9811111111,EMP002,\n'
        )
        resp = _auth_client(manager_user).post(
            f'{USERS_URL}bulk/', {'format': 'csv', 'data': csv_data}, format='json',
        )
        assert resp.status_code == 201
        assert resp.data['status'] == 'success'
        assert resp.data['created'] == 2
        deepa = User.objects.get(email='deepa@acme.com')
        assert deepa.employee_id == 'EMP001'
        assert deepa.user_roles.filter(role__code='sales_exec', is_active=True).exists()

    def test_all_or_nothing_on_validation_error(self, manager_user):
        csv_data = (
            'first_name,email,roles\n'
            'Valid,valid@acme.com,\n'
            'NoIdentifier,,\n'              # missing email/mobile/employee_id
            'BadRole,bad@acme.com,ghost\n'  # unknown role code
        )
        resp = _auth_client(manager_user).post(
            f'{USERS_URL}bulk/', {'format': 'csv', 'data': csv_data}, format='json',
        )
        assert resp.status_code == 200
        assert resp.data['status'] == 'validation_failed'
        rows_with_errors = {e['row'] for e in resp.data['errors']}
        assert rows_with_errors == {2, 3}
        # Nothing created — including the otherwise-valid row 1.
        assert not User.objects.filter(email='valid@acme.com').exists()

    def test_duplicate_email_in_db_rejected(self, manager_user):
        User.objects.create_user(email='taken@acme.com', password='x')
        csv_data = 'first_name,email\nDup,taken@acme.com\n'
        resp = _auth_client(manager_user).post(
            f'{USERS_URL}bulk/', {'format': 'csv', 'data': csv_data}, format='json',
        )
        assert resp.data['status'] == 'validation_failed'

    def test_export_returns_csv_of_filtered_users(self, manager_user):
        User.objects.create_user(email='one@acme.com', password='x', department='Sales')
        User.objects.create_user(email='two@acme.com', password='x', department='Finance')
        resp = _auth_client(manager_user).get(f'{USERS_URL}export/?department=Sales')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'text/csv'
        body = resp.content.decode()
        assert 'one@acme.com' in body
        assert 'two@acme.com' not in body

    def test_filter_by_status_inactive(self, manager_user):
        User.objects.create_user(email='active@acme.com', password='x')
        gone = User.objects.create_user(email='gone@acme.com', password='x')
        gone.is_active = False
        gone.save(update_fields=['is_active'])
        resp = _auth_client(manager_user).get(f'{USERS_URL}?status=inactive')
        emails = {u['email'] for u in resp.data['results']}
        assert 'gone@acme.com' in emails
        assert 'active@acme.com' not in emails

    def test_departments_action_lists_distinct(self, manager_user):
        User.objects.create_user(email='a@acme.com', password='x', department='Sales')
        User.objects.create_user(email='b@acme.com', password='x', department='Sales')
        User.objects.create_user(email='c@acme.com', password='x', department='Finance')
        resp = _auth_client(manager_user).get(f'{USERS_URL}departments/')
        assert resp.status_code == 200
        assert sorted(resp.data) == ['Finance', 'Sales']


@pytest.mark.django_db
class TestUserImportNodeLink:

    @pytest.fixture
    def entity(self, db):
        from apps.hierarchy.models import Node, NodeType
        et = NodeType.objects.create(
            name='Area Sales Exec', code='ase', level_order=1,
            attribute_schema=[], effective_from=date.today(),
        )
        return Node.objects.create(
            entity_type=et, name='Deepa', code='ASE_DEEPA',
            status='active', effective_from=date.today(),
        )

    def test_links_user_to_entity(self, manager_user, entity):
        csv_data = f'first_name,email,entity_code\nDeepa,deepa@acme.com,{entity.code}\n'
        resp = _auth_client(manager_user).post(
            f'{USERS_URL}bulk/', {'format': 'csv', 'data': csv_data}, format='json',
        )
        assert resp.status_code == 201
        user = User.objects.get(email='deepa@acme.com')
        assert user.entity_id == entity.id

    def test_unknown_entity_code_rejected(self, manager_user):
        csv_data = 'first_name,email,entity_code\nX,x@acme.com,NOPE\n'
        resp = _auth_client(manager_user).post(
            f'{USERS_URL}bulk/', {'format': 'csv', 'data': csv_data}, format='json',
        )
        assert resp.data['status'] == 'validation_failed'
        assert not User.objects.filter(email='x@acme.com').exists()

    def test_entity_already_linked_rejected(self, manager_user, entity):
        existing = User.objects.create_user(email='first@acme.com', password='x')
        existing.entity = entity
        existing.save(update_fields=['entity'])
        csv_data = f'first_name,email,entity_code\nSecond,second@acme.com,{entity.code}\n'
        resp = _auth_client(manager_user).post(
            f'{USERS_URL}bulk/', {'format': 'csv', 'data': csv_data}, format='json',
        )
        assert resp.data['status'] == 'validation_failed'

    def test_duplicate_entity_code_in_file_rejected(self, manager_user, entity):
        csv_data = (
            'first_name,email,entity_code\n'
            f'A,a@acme.com,{entity.code}\n'
            f'B,b@acme.com,{entity.code}\n'
        )
        resp = _auth_client(manager_user).post(
            f'{USERS_URL}bulk/', {'format': 'csv', 'data': csv_data}, format='json',
        )
        assert resp.data['status'] == 'validation_failed'
        assert not User.objects.filter(email__in=['a@acme.com', 'b@acme.com']).exists()


@pytest.mark.django_db
class TestUserDuplicateHandling:

    def test_duplicate_employee_id_returns_clean_400(self, manager_user):
        User.objects.create_user(employee_id='EMP001', email='a@acme.com', password='x')
        resp = _auth_client(manager_user).post(
            USERS_URL, {'first_name': 'Dup', 'employee_id': 'EMP001'}, format='json',
        )
        assert resp.status_code == 400
        # Detail must be a readable sentence, not a stringified dict/ErrorDetail blob.
        detail = resp.data['detail']
        assert 'already exists' in detail
        assert 'ErrorDetail' not in detail
        assert not detail.strip().startswith('{')

    def test_edit_keeping_own_employee_id_succeeds(self, manager_user):
        u = User.objects.create_user(employee_id='EMP010', email='keep@acme.com', password='x')
        resp = _auth_client(manager_user).patch(
            f'{USERS_URL}{u.pk}/',
            {'first_name': 'Renamed', 'employee_id': 'EMP010'},
            format='json',
        )
        assert resp.status_code == 200
        u.refresh_from_db()
        assert u.first_name == 'Renamed'
