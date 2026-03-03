from typing import List
from django.urls import URLPattern, path

from .views.campaign import campaign_preview_form, CampaignPreviewView
from .views.document import (
    CampaignDocumentDownloadView,
    MissiveDocumentDownloadView,
)
from .views.missive import missive_preview_form, MissivePreviewView
from .views.webhook import WebhookView

app_name = "django_pymissive"

urlpatterns: List[URLPattern] = [
    path(
        "missive/<uuid:pk>/preview/",
        MissivePreviewView.as_view(),
        name="missive_preview",
    ),
    path("missive/preview/", missive_preview_form, name="missive_preview_form"),
    path(
        "campaign/<uuid:pk>/preview/",
        CampaignPreviewView.as_view(),
        name="campaign_preview",
    ),
    path("campaign/preview/", campaign_preview_form, name="campaign_preview_form"),
    path(
        "webhook/<str:provider>/<str:missive_type>/",
        WebhookView.as_view(),
        name="missive_webhook",
    ),
    path(
        "missive-document/<uuid:pk>/download/",
        MissiveDocumentDownloadView.as_view(),
        name="missive_document_download",
    ),
    path(
        "campaign-document/<uuid:pk>/download/",
        CampaignDocumentDownloadView.as_view(),
        name="campaign_document_download",
    ),
]
