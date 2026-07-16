from django.apps import AppConfig


class IncentivesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.incentives'
    label = 'incentives'

    def ready(self):
        # Register workflow subject adapters so the generic engine can route/finalize
        # PayoutException and PayoutRun without importing this app.
        from . import adapters
        adapters.register()
