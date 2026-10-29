"""A campaign target opens the same preview as a missive, without saving one."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

import pytest

from django_pymissive.models import CampaignTarget, Missive, MissiveCampaign, MissiveStatus, MissiveType
from django_pymissive.models.choices import MissiveRecipientType
from django_pymissive.services import select
from tests.fakeapp.models import Contact

pytestmark = pytest.mark.django_db


def _campaign():
    return MissiveCampaign.objects.create(
        subject="Assemblée",
        email_body_rich="<p>token-{{ contact.id }}</p>",
        email_body_text="Bonjour",
    )


def _staff(username, *, view=True):
    user = get_user_model().objects.create_user(username=username, password="x", is_staff=True)
    if view:
        user.user_permissions.add(Permission.objects.get(codename="view_campaigntarget"))
        user = get_user_model().objects.get(pk=user.pk)
    return user


def _row():
    campaign = _campaign()
    contact = Contact.objects.create(first_name="Ada", last_name="Lovelace", email="ada-preview@example.com")
    select(campaign, "email", contact)
    return CampaignTarget.objects.get(campaign=campaign), contact


def test_target_preview_renders_the_contact_and_saves_nothing():
    row, contact = _row()
    row.add_recipient(
        {"name": "Grace", "email": "grace-preview@example.com"},
        recipient_type=MissiveRecipientType.CC,
    )
    user = _staff("preview-target")
    client = Client()
    client.force_login(user)

    response = client.get(reverse("django_pymissive:preview_target", args=[row.pk]))

    assert response.status_code == 200
    html = response.content.decode()
    assert f"token-{contact.pk}" in html
    assert "ada-preview@example.com" in html
    assert "grace-preview@example.com" in html
    assert Missive.objects.count() == 0
    assert CampaignTarget.objects.get(pk=row.pk).missive_id is None


def test_target_preview_is_staff_only():
    row, _contact = _row()
    url = reverse("django_pymissive:preview_target", args=[row.pk])

    anonymous = Client().get(url)
    assert anonymous.status_code == 302
    assert "login" in anonymous.url

    client = Client()
    client.force_login(_staff("preview-no-right", view=False))
    assert client.get(url).status_code == 403


def test_target_with_a_missive_uses_that_preview():
    row, _contact = _row()
    missive = Missive.objects.create(
        campaign=row.campaign,
        missive_type=MissiveType.EMAIL,
        subject="Déjà rédigé",
        body_rich="<p>Déjà rédigé</p>",
        status=MissiveStatus.DRAFT,
    )
    row.attach_missive(missive)
    model_admin = admin.site._registry[CampaignTarget]

    assert row.get_browser_preview_path() == missive.get_browser_preview_path()
    assert model_admin.preview._admin_boost_config["view_type"] == "redirect"

    client = Client()
    client.force_login(_staff("preview-existing"))
    response = client.get(reverse("django_pymissive:preview_target", args=[row.pk]))

    assert response.status_code == 302
    assert response.url == missive.get_browser_preview_path()
