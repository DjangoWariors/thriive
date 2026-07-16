from .base import *

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
]
CORS_ALLOW_CREDENTIALS = True

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Throttling is a production concern; disable the rate limits locally and in the
# test suite so neither the dev server nor the many auth/bulk tests get 429'd.
# Focused throttle tests opt back in with @override_settings.
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {'auth': None, 'otp': None, 'bulk': None, 'integration': None}

# No broker in dev — run Celery work inline (synchronously) and surface errors.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
