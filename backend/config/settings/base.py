from datetime import timedelta
from pathlib import Path

from celery.schedules import crontab
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-this-in-production')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'corsheaders',
    'django_celery_beat',
]

LOCAL_APPS = [
    'apps.core',
    'apps.jobs',
    'apps.accounts',
    'apps.hierarchy',
    'apps.assignments',
    'apps.master_data',
    'apps.kpi_engine',
    'apps.targets',
    'apps.achievements',
    'apps.incentives',
    'apps.workflows',
    'apps.notifications',
    'apps.audit',
    'apps.reports',
    'apps.admin_console',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.core.middleware.RequestIDMiddleware',
    'apps.audit.middleware.AuditMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='thriive_dev'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

AUTH_USER_MODEL = 'accounts.User'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# In-process cache by default (dev/test need no Redis). prod.py swaps in Redis.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'thriive-default',
    }
}

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        # Machine integrations: X-API-Key header, no-ops when the header is absent.
        'apps.accounts.authentication.ApiKeyAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': ['apps.core.permissions.RBACPermission'],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'apps.core.pagination.StandardPagination',
    'PAGE_SIZE': 25,
    'EXCEPTION_HANDLER': 'apps.core.exceptions.custom_exception_handler',
    # ScopedRateThrottle only throttles views that declare `throttle_scope`,
    # so this default is a no-op everywhere except the auth/OTP endpoints that
    # opt in. Bulk-import actions use BulkImportRateThrottle (scope 'bulk').
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.ScopedRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {
        'auth': config('THRIIVE_THROTTLE_AUTH', default='20/min'),
        'otp': config('THRIIVE_THROTTLE_OTP', default='5/min'),
        'bulk': config('THRIIVE_THROTTLE_BULK', default='5/hour'),
        'integration': config('THRIIVE_THROTTLE_INTEGRATION', default='120/min'),
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Thriive IMS API',
    'DESCRIPTION': 'Enterprise Channel Incentive & Loyalty Management Platform',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'PREPROCESSING_HOOKS': ['apps.core.schema.filter_admin_urls'],
    'APPEND_COMPONENTS': {
        'securitySchemes': {
            'BearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}
        }
    },
    'SECURITY': [{'BearerAuth': []}],
}

CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('REDIS_URL', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Kolkata'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
# Celery's built-in default queue is named 'celery'. The workers consume named queues
# (deploy/supervisor/thriive.conf), so anything CELERY_TASK_ROUTES doesn't route must land
# on one of them — otherwise it is published to a queue nobody listens to and never runs.
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TASK_ROUTES = {
    'apps.achievements.tasks.*': {'queue': 'achievements'},
    'apps.incentives.tasks.*': {'queue': 'payouts'},
    'apps.reports.tasks.*': {'queue': 'reports'},
}
CELERY_BEAT_SCHEDULE = {
    'escalate-overdue-workflows': {
        'task': 'apps.workflows.tasks.escalate_overdue_workflows',
        'schedule': 900.0,  # every 15 minutes — applies overdue steps' SLA policy
    },
    'send-workflow-reminders': {
        'task': 'apps.workflows.tasks.send_workflow_reminders',
        'schedule': 3600.0,  # hourly — nudge approvers nearing their SLA
    },
    'compute-daily-achievements': {
        'task': 'apps.achievements.tasks.run_scheduled_achievements',
        # Nightly: recompute every currently-live period (see auto-statuses below).
        'schedule': crontab(hour=config('THRIIVE_ACHIEVEMENT_CRON_HOUR', default=2, cast=int),
                            minute=0),
    },
    'compute-payout-estimates': {
        'task': 'apps.incentives.tasks.run_scheduled_estimates',
        # Nightly, after achievements: refresh estimate payouts for every open cycle.
        'schedule': crontab(hour=config('THRIIVE_ESTIMATE_CRON_HOUR', default=3, cast=int),
                            minute=0),
    },
    'sweep-log-retention': {
        'task': 'apps.audit.tasks.sweep_retention',
        # Nightly: apply RetentionPolicy deletes to audit/access/computation logs.
        'schedule': crontab(hour=config('THRIIVE_RETENTION_CRON_HOUR', default=4, cast=int),
                            minute=0),
    },
}

# Which TargetPeriod statuses the nightly achievement run recomputes. Client-tunable
# (no code change) — e.g. drop 'locked' to treat locked periods as finalized.
THRIIVE_ACHIEVEMENT_AUTO_STATUSES = config(
    'THRIIVE_ACHIEVEMENT_AUTO_STATUSES', default='published,locked', cast=Csv())

THRIIVE_OTP_LENGTH = config('THRIIVE_OTP_LENGTH', default=6, cast=int)
THRIIVE_OTP_EXPIRY_SECONDS = config('THRIIVE_OTP_EXPIRY_SECONDS', default=300, cast=int)
THRIIVE_OTP_RATE_LIMIT = config('THRIIVE_OTP_RATE_LIMIT', default=5, cast=int)
THRIIVE_MAX_LOGIN_ATTEMPTS = config('THRIIVE_MAX_LOGIN_ATTEMPTS', default=5, cast=int)
THRIIVE_LOCKOUT_MINUTES = config('THRIIVE_LOCKOUT_MINUTES', default=30, cast=int)
