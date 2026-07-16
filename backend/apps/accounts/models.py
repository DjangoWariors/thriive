from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from apps.core.models import BaseModel


class UserManager(BaseUserManager):
    def create_user(self, email=None, mobile=None, employee_id=None, password=None, **extra_fields):
        user = self.model(email=email, mobile=mobile, employee_id=employee_id, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email=email, password=password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, null=True, blank=True)
    mobile = models.CharField(max_length=20, unique=True, null=True, blank=True)
    employee_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    designation = models.CharField(max_length=200, blank=True)
    department = models.CharField(max_length=200, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    failed_login_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    entity = models.OneToOneField(
        'hierarchy.Node',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='user',
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = 'accounts_user'

    def __str__(self):
        return self.email or self.mobile or self.employee_id or f'User {self.pk}'


class Role(BaseModel):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    permissions = models.JSONField(default=dict)
    is_system_role = models.BooleanField(default=False)

    class Meta:
        db_table = 'accounts_role'

    def __str__(self):
        return self.name


class UserRole(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_roles')
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'accounts_userrole'

    def __str__(self):
        return f'{self.user} — {self.role}'


class OTPToken(models.Model):
    identifier = models.CharField(max_length=255, db_index=True)
    otp = models.CharField(max_length=10)
    purpose = models.CharField(max_length=50)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounts_otptoken'
        indexes = [
            models.Index(fields=['identifier', 'purpose', 'is_used']),
        ]

    def __str__(self):
        return f'OTP for {self.identifier} ({self.purpose})'


class APIKey(BaseModel):
    """Machine credential for integration pushes (DMS/SFA/agency feeds).
    The plaintext secret is returned exactly once at issue time; only its sha256
    is stored. A key authenticates AS its linked service-account ``user``, so
    RBAC, scoping and audit attribution work unchanged. Revoking = deactivating.
    """

    name = models.CharField(max_length=200)
    key_prefix = models.CharField(max_length=12, db_index=True)
    hashed_key = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'accounts_apikey'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.key_prefix}…)'


class LoginAttempt(models.Model):
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='login_attempts',
    )
    identifier = models.CharField(max_length=255)
    method = models.CharField(max_length=20)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    success = models.BooleanField()
    failure_reason = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounts_loginattempt'
        indexes = [
            models.Index(fields=['identifier', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
        ]

    def __str__(self):
        status = 'OK' if self.success else 'FAIL'
        return f'{self.identifier} [{self.method}] {status}'
