"""API-key authentication for machine integrations.

``X-API-Key: <prefix>.<secret>`` authenticates as the key's service-account
user, so RBAC, scoping and audit attribution behave exactly as for a person.
Requests without the header fall through to the next authenticator (JWT).
"""
import hashlib
import hmac

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import APIKey

_HEADER = 'HTTP_X_API_KEY'


class ApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        raw = request.META.get(_HEADER)
        if not raw:
            return None
        prefix, _, secret = raw.partition('.')
        if not prefix or not secret:
            raise AuthenticationFailed('Malformed API key.')

        key = (
            APIKey.objects.filter(key_prefix=prefix, is_active=True)
            .select_related('user')
            .first()
        )
        digest = hashlib.sha256(secret.encode()).hexdigest()
        # Compare unconditionally — against itself on a prefix miss — so unknown
        # prefixes and bad secrets are indistinguishable by timing.
        match = hmac.compare_digest(digest, key.hashed_key if key else digest)
        if key is None or not match:
            raise AuthenticationFailed('Invalid API key.')
        if key.expires_at and key.expires_at <= timezone.now():
            raise AuthenticationFailed('API key has expired.')
        if not key.user.is_active:
            raise AuthenticationFailed('Service account is inactive.')

        APIKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        return (key.user, key)

    def authenticate_header(self, request):
        return 'Api-Key'
