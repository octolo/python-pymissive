from django.apps import AppConfig


class DjangoPymissiveConfig(AppConfig):
    """Django Pymissive app configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_pymissive"
    verbose_name = "Django Missive"

    def ready(self):
        """Imports signal handlers when app is ready."""
        # Import signals or other initialization here if needed
