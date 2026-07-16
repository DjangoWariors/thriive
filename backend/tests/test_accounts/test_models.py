import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts.models import LoginAttempt, OTPToken, Role, User, UserRole


@pytest.mark.django_db
class TestUser:
    def test_create_user_with_email(self):
        user = User.objects.create_user(email='test@example.com', password='pass123')
        assert user.email == 'test@example.com'
        assert user.check_password('pass123')
        assert user.is_active
        assert not user.is_staff
        assert not user.is_superuser

    def test_create_user_with_mobile(self):
        user = User.objects.create_user(mobile='9876543210')
        assert user.mobile == '9876543210'
        assert not user.has_usable_password()

    def test_create_user_with_employee_id(self):
        user = User.objects.create_user(employee_id='EMP001', password='pass123')
        assert user.employee_id == 'EMP001'

    def test_create_user_no_password_sets_unusable(self):
        user = User.objects.create_user(email='nopw@example.com')
        assert not user.has_usable_password()

    def test_create_superuser_flags(self):
        su = User.objects.create_superuser(email='admin@example.com', password='adminpass')
        assert su.is_staff
        assert su.is_superuser

    def test_duplicate_email_raises_integrity_error(self):
        User.objects.create_user(email='dup@example.com', password='pass')
        with pytest.raises(IntegrityError):
            User.objects.create_user(email='dup@example.com', password='pass2')

    def test_duplicate_mobile_raises_integrity_error(self):
        User.objects.create_user(mobile='9000000001')
        with pytest.raises(IntegrityError):
            User.objects.create_user(mobile='9000000001')

    def test_duplicate_employee_id_raises_integrity_error(self):
        User.objects.create_user(employee_id='EMP999')
        with pytest.raises(IntegrityError):
            User.objects.create_user(employee_id='EMP999')

    def test_soft_delete_via_is_active(self):
        user = User.objects.create_user(email='active@example.com', password='pass')
        user.is_active = False
        user.save()
        assert not User.objects.get(pk=user.pk).is_active

    def test_str_returns_email(self):
        user = User.objects.create_user(email='str@example.com')
        assert str(user) == 'str@example.com'

    def test_str_falls_back_to_mobile(self):
        user = User.objects.create_user(mobile='9111111111')
        assert str(user) == '9111111111'

    def test_str_falls_back_to_employee_id(self):
        user = User.objects.create_user(employee_id='EMP_STR')
        assert str(user) == 'EMP_STR'


@pytest.mark.django_db
class TestRole:
    def test_create_role(self):
        role = Role.objects.create(name='Admin', code='admin', permissions={'dashboard': 'full'})
        assert role.is_active
        assert not role.is_system_role
        assert role.permissions == {'dashboard': 'full'}

    def test_unique_code_constraint(self):
        Role.objects.create(name='Role A', code='role_a')
        with pytest.raises(IntegrityError):
            Role.objects.create(name='Role B', code='role_a')


@pytest.mark.django_db
class TestUserRole:
    def test_create_user_role(self):
        user = User.objects.create_user(email='ur@example.com')
        role = Role.objects.create(name='Sales', code='sales')
        from datetime import date
        ur = UserRole.objects.create(user=user, role=role, effective_from=date.today())
        assert ur.is_active
        assert ur.effective_to is None


@pytest.mark.django_db
class TestOTPToken:
    def test_create_otp_token(self):
        expires = timezone.now() + timezone.timedelta(minutes=5)
        token = OTPToken.objects.create(
            identifier='9876543210',
            otp='123456',
            purpose='login',
            expires_at=expires,
        )
        assert not token.is_used
        assert token.attempts == 0
        assert token.max_attempts == 3

    def test_otp_str(self):
        expires = timezone.now() + timezone.timedelta(minutes=5)
        token = OTPToken.objects.create(
            identifier='test@x.com', otp='654321', purpose='login', expires_at=expires
        )
        assert 'test@x.com' in str(token)


@pytest.mark.django_db
class TestLoginAttempt:
    def test_create_success_attempt(self):
        user = User.objects.create_user(email='login@example.com', password='pass')
        attempt = LoginAttempt.objects.create(
            user=user,
            identifier='login@example.com',
            method='password',
            success=True,
        )
        assert attempt.success
        assert attempt.failure_reason == ''

    def test_create_failed_attempt_no_user(self):
        attempt = LoginAttempt.objects.create(
            user=None,
            identifier='unknown@example.com',
            method='password',
            success=False,
            failure_reason='user_not_found',
        )
        assert not attempt.success
        assert attempt.user is None

    def test_str(self):
        attempt = LoginAttempt.objects.create(
            identifier='rep@x.com', method='otp', success=True
        )
        assert 'rep@x.com' in str(attempt)
        assert 'OK' in str(attempt)
