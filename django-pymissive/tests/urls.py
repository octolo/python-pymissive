"""URL configuration for tests."""

import django
import pymissive
import django_pymissive
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from django.conf import settings


urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    path("geoaddress/", include("django_geoaddress.urls")),
    path("missive/", include("django_pymissive.urls")),

]

if settings.DEBUG:
    try:
        import debug_toolbar  # noqa: F401

        urlpatterns = [
            path("__debug__/", include("debug_toolbar.urls")),
        ] + urlpatterns
    except ImportError:
        pass

try:
    import djrichtextfield
    urlpatterns += [
        path('djrichtextfield/', include('djrichtextfield.urls'))
    ]
except ImportError:
    pass

_version = f"(Django {django.get_version()}, pymissive (py/dj) {pymissive.__version__}/{django_pymissive.__version__})"
admin.site.site_header = f"Django Pymissive - Administration {_version}"
admin.site.site_title = f"Django Pymissive Admin {_version}"
admin.site.index_title = f"Welcome to Django Pymissive {_version}"

if hasattr(settings, "NGROK_PUBLIC_URL") and settings.NGROK_PUBLIC_URL:
    admin.site.site_header += f" - {settings.NGROK_PUBLIC_URL}"
