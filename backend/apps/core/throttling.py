from rest_framework.throttling import UserRateThrottle


class BulkImportRateThrottle(UserRateThrottle):
    """Caps expensive bulk-import calls per user. Rate comes from
    REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['bulk'] (default 5/hour)."""

    scope = 'bulk'


class IntegrationRateThrottle(UserRateThrottle):
    """Caps machine push endpoints (transactions / metric values) per service
    account. Rate comes from DEFAULT_THROTTLE_RATES['integration'] (120/min)."""

    scope = 'integration'
