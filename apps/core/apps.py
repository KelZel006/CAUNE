from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Núcleo CAUNE"

    def ready(self):
        from . import signals  # noqa: F401
