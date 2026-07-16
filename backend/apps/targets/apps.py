from django.apps import AppConfig


class TargetsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.targets'
    label = 'targets'

    def ready(self):
        from . import adapters
        adapters.register()
