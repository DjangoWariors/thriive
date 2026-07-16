"""Unit tests for User serializer computed fields."""
from types import SimpleNamespace

from apps.accounts.serializers import UserSerializer


class TestPortalType:
    """portal_type must always resolve to 'admin' | 'partner' — never null —
    since the frontend layout router depends on it."""

    def setup_method(self):
        self.ser = UserSerializer()

    def test_admin_when_no_entity(self):
        user = SimpleNamespace(entity=None)
        assert self.ser.get_portal_type(user) == 'admin'

    def test_admin_when_entity_type_missing(self):
        user = SimpleNamespace(entity=SimpleNamespace(entity_type=None))
        assert self.ser.get_portal_type(user) == 'admin'

    def test_admin_default_when_display_config_unset(self):
        etype = SimpleNamespace(display_config=None)
        user = SimpleNamespace(entity=SimpleNamespace(entity_type=etype))
        assert self.ser.get_portal_type(user) == 'admin'

    def test_partner_from_display_config(self):
        etype = SimpleNamespace(display_config={'portal_type': 'partner'})
        user = SimpleNamespace(entity=SimpleNamespace(entity_type=etype))
        assert self.ser.get_portal_type(user) == 'partner'
