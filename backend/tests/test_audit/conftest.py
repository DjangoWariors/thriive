from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User, UserRole

_seq = iter(range(1_000_000))


def make_user(email, *, entity=None, perms=None, superuser=False):
    if superuser:
        return User.objects.create_superuser(email=email, password='pass')
    user = User.objects.create_user(email=email, password='pass', entity=entity)
    if perms:
        code = f'aur{next(_seq)}'
        role = Role.objects.create(code=code, name=code, permissions=perms)
        UserRole.objects.create(user=user, role=role, effective_from=date.today())
    return user


def client_for(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


@pytest.fixture
def auditor(db):
    return make_user('auditor@x.com', perms={'audit_logs': 'view_all', 'audit_access': 'view_all'})
