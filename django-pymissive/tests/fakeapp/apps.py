from django.apps import AppConfig


class FakeappConfig(AppConfig):
    """Tiny in-tree app used to exercise the virtual attachment machinery.

    Lives under ``tests/fakeapp/`` so it is only loaded by the test
    project's ``DJANGO_SETTINGS_MODULE``. Not packaged or shipped.
    """

    name = "tests.fakeapp"
    label = "fakeapp"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Test Fake App"
