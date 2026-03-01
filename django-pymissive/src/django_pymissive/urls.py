from typing import List
from django.urls import URLPattern, path

from .views.missive import missive_preview_form, MissivePreviewView
from .views.webhook import WebhookView
from .views.document import DocumentDownloadView

app_name = "django_pymissive"

urlpatterns: List[URLPattern] = [
    path(
        "missive/<uuid:pk>/preview/",
        MissivePreviewView.as_view(),
        name="missive_preview",
    ),
    path("missive/preview/", missive_preview_form, name="missive_preview_form"),
    path(
        "webhook/<str:provider>/<str:missive_type>/",
        WebhookView.as_view(),
        name="missive_webhook",
    ),
    path(
        "document/<uuid:pk>/download/",
        DocumentDownloadView.as_view(),
        name="document_download",
    ),
]
