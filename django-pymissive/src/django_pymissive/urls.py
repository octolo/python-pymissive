from typing import List

from django.urls import URLPattern, path

from .views.attachment import MissiveAttachmentDownloadView
from .views.preview import PreviewFormView, PreviewView
from .views.webhook import WebhookView

app_name = "django_pymissive"

urlpatterns: List[URLPattern] = [
    path(
        "preview/<str:campaign_or_missive>/<uuid:pk>/",
        PreviewView.as_view(),
        name="preview",
    ),
    path(
        "preview/<str:campaign_or_missive>/",
        PreviewFormView.as_view(),
        name="preview_form",
    ),
    path(
        "webhook/<str:provider>/<str:missive_type>/",
        WebhookView.as_view(),
        name="missive_webhook",
    ),
    path(
        "attachment/<str:campaign_or_missive>/<uuid:pk>/download/",
        MissiveAttachmentDownloadView.as_view(),
        name="missive_attachment_download",
    ),
]
