"""Branded preview picks a template from the provider and renders the message."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.views.preview import template_for_missive

pytestmark = pytest.mark.django_db


def test_branded_template_follows_the_provider():
    discord = Missive(missive_type=MissiveType.BRANDED, provider="discord")
    slack = Missive(missive_type=MissiveType.BRANDED, provider="slack")
    teams = Missive(missive_type=MissiveType.BRANDED, provider="teams")

    assert template_for_missive(discord)[0] == "django_pymissive/branded/discord_preview.html"
    assert template_for_missive(slack)[0] == "django_pymissive/branded/slack_preview.html"
    assert template_for_missive(teams)[0] == "django_pymissive/branded/teams_preview.html"
    assert template_for_missive(discord)[-1] == "django_pymissive/branded_preview.html"


def test_unknown_or_unsafe_brand_uses_the_generic_template():
    unknown = Missive(missive_type=MissiveType.BRANDED, provider="whatsapp")
    unsafe = Missive(missive_type=MissiveType.BRANDED, provider="../secret")

    assert template_for_missive(unknown) == ["django_pymissive/branded_preview.html"]
    assert template_for_missive(unsafe) == ["django_pymissive/branded_preview.html"]


def test_notification_sent_through_discord_uses_the_discord_template():
    """The application is the provider, not the missive type."""
    missive = Missive(
        missive_type=MissiveType.NOTIFICATION,
        provider="discord",
        brand_name="Octolo",
    )

    assert template_for_missive(missive)[0] == "django_pymissive/branded/discord_preview.html"


def test_other_missive_types_keep_their_template():
    email = Missive(missive_type=MissiveType.EMAIL)
    assert template_for_missive(email) == ["django_pymissive/email_preview.html"]


def test_discord_preview_renders_the_message_and_escapes_html():
    missive = Missive.objects.create(
        missive_type=MissiveType.BRANDED,
        provider="discord",
        brand_name="Octolo",
        body_text="Bonjour\nhttps://example.com <script>alert(1)</script>",
        status=MissiveStatus.DRAFT,
    )
    url = reverse("django_pymissive:preview", args=["missive", missive.pk])

    response = Client().get(url)

    assert response.status_code == 200
    html = response.content.decode()
    assert "brand-discord" in html
    assert "branded/discord_preview.css" in html
    assert "Octolo" in html
    assert "BOT" in html
    assert "https://example.com" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_discord_notification_preview_shows_the_rich_body():
    missive = Missive.objects.create(
        missive_type=MissiveType.NOTIFICATION,
        provider="discord",
        brand_name="Octolo",
        body_rich="<b>test</b>",
        status=MissiveStatus.DRAFT,
    )
    url = reverse("django_pymissive:preview", args=["missive", missive.pk])

    response = Client().get(url)

    assert response.status_code == 200
    html = response.content.decode()
    assert "brand-discord" in html
    assert "Octolo" in html
    assert ">test<" in html or "test" in html
    assert "<b>" not in html
    assert "Best regards" not in html


def test_campaign_preview_uses_the_brand_and_the_app_body():
    campaign = MissiveCampaign.objects.create(
        subject="Compte rendu",
        phone_body_text="Le document est prêt.",
    )
    url = reverse("django_pymissive:preview", args=["campaign", campaign.pk])

    response = Client().get(url, {"type": "branded", "brand": "teams"})

    assert response.status_code == 200
    html = response.content.decode()
    assert "brand-teams" in html
    assert "branded/teams_preview.css" in html
    assert "Compte rendu" in html
    assert "Le document est prêt." in html


def test_campaign_preview_rejects_an_unknown_brand():
    campaign = MissiveCampaign.objects.create(subject="Compte rendu", phone_body_text="OK")
    url = reverse("django_pymissive:preview", args=["campaign", campaign.pk])

    response = Client().get(url, {"type": "branded", "brand": "../../etc"})

    assert response.status_code == 200
    assert "brand-generic" in response.content.decode()


def test_unsaved_branded_missive_preview_url_carries_the_brand():
    campaign = MissiveCampaign.objects.create(subject="Hello")
    missive = Missive(campaign=campaign, missive_type=MissiveType.BRANDED, provider="slack")

    path = missive.get_browser_preview_path()

    assert "type=branded" in path
    assert "brand=slack" in path
