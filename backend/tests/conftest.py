import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """DRF stores rate-limit history in the default cache (LocMemCache in tests).
    Clear it around every test so throttle state never leaks between tests."""
    cache.clear()
    yield
    cache.clear()
