"""Admin search fields resolve, related-object labels are escaped, and proof download validates."""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory

from django_pymissive.admin.campaign import MissiveCampaignAdmin
from django_pymissive.admin.related_object import MissiveRelatedObjectAdmin
from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.models.related_object import CampaignRelatedObject, MissiveRelatedObject

pytestmark = pytest.mark.django_db


def _missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "status": MissiveStatus.DRAFT,
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def _request(**params):
    request = RequestFactory().get("/", params)
    request.user = get_user_model()(is_superuser=True, is_staff=True)
    return request


def _superuser_request(method="get", **params):
    request = getattr(RequestFactory(), method)("/", params)
    request.user = get_user_model().objects.create_superuser(username="admin", email="admin@example.com", password="x")
    return request


def test_all_admin_search_fields_are_queryable():
    """Every registered admin's search box must build a runnable query.

    ``search_fields`` is not covered by Django's system checks, so a stale field
    name only surfaces as a 500 when someone types in the search box.
    """
    failures = []
    for model, model_admin in admin.site._registry.items():
        if not model_admin.search_fields:
            continue
        try:
            queryset, _duplicates = model_admin.get_search_results(_request(q="x"), model._default_manager.all(), "x")
            list(queryset[:1])
        except Exception as exc:
            failures.append(f"{model._meta.label}: {type(exc).__name__}: {exc}")

    assert not failures, "unqueryable search_fields:\n" + "\n".join(failures)


def test_related_object_link_escapes_object_str():
    user = get_user_model().objects.create_user(username="target", password="x")
    related = MissiveRelatedObject.objects.create(
        missive=_missive(),
        content_type=ContentType.objects.get_for_model(user),
        object_id=str(user.pk),
    )
    MissiveRelatedObject.objects.filter(pk=related.pk).update(object_str="<img src=x onerror=alert(1)>")
    related.refresh_from_db()

    rendered = MissiveRelatedObjectAdmin(MissiveRelatedObject, admin.site).object_url_link_display(related)

    assert "<img" not in rendered
    assert "&lt;img" in rendered


def test_campaign_admin_searches_and_displays_related_objects():
    campaign = MissiveCampaign.objects.create(subject="Campaign")
    content_type = ContentType.objects.get_for_model(get_user_model())
    for username in ("first-related", "second-related", "third-related"):
        user = get_user_model().objects.create_user(username=username)
        CampaignRelatedObject.objects.create(
            campaign=campaign,
            content_type=content_type,
            object_id=str(user.pk),
        )

    campaign_admin = MissiveCampaignAdmin(MissiveCampaign, admin.site)
    queryset = campaign_admin.get_queryset(_request())
    result, _duplicates = campaign_admin.get_search_results(
        _request(q="second-related"),
        queryset,
        "second-related",
    )
    campaign = queryset.get(pk=campaign.pk)
    rendered = campaign_admin.related_objects_display(campaign)

    assert list(result) == [campaign]
    assert "third-related" in rendered
    assert "second-related" in rendered
    assert "first-related" not in rendered
    assert "<span>+1</span>" in rendered
    assert 'boost-label' not in rendered[rendered.index("+1") - 20 :]
    assert "flex-direction:column" in rendered
    assert "align-items:center" in rendered
    assert "text-overflow:ellipsis" in rendered
    assert 'title="third-related"' in rendered


def test_every_inline_links_to_its_change_page():
    """Proxy inlines open the registered concrete model; the link is on the page."""
    from django.contrib.admin.options import InlineModelAdmin
    from django.test import Client
    from django.urls import reverse
    from django_pymissive.models.campaign_step import CampaignStep, EmailCampaignStep
    from django_pymissive.models.recipient import MissiveRecipientEmail

    step_inline = None
    for model, model_admin in admin.site._registry.items():
        if model._meta.app_label != "django_pymissive":
            continue
        for inline_class in model_admin.inlines:
            assert issubclass(inline_class, InlineModelAdmin)
            assert inline_class.show_change_link, inline_class
            inline = inline_class(model, admin.site)
            assert inline.change_link_url_name, inline_class
            if inline.model is EmailCampaignStep:
                step_inline = inline

    assert EmailCampaignStep not in admin.site._registry
    assert step_inline is not None
    assert step_inline.change_link_url_name.endswith("campaignstep_change")

    user = get_user_model().objects.create_superuser(
        username="inline-link",
        email="inline-link@example.com",
        password="x",
    )
    client = Client()
    client.force_login(user)
    campaign = MissiveCampaign.objects.create(subject="Launch")
    step = CampaignStep.objects.create(
        campaign=campaign,
        position=1,
        missive_type=MissiveType.EMAIL,
        label="Email",
    )
    page = client.get(reverse("admin:django_pymissive_missivecampaign_change", args=[campaign.pk]))
    assert page.status_code == 200
    assert reverse("admin:django_pymissive_campaignstep_change", args=[step.pk]).encode() in page.content
    assert b"inlinechangelink" in page.content

    missive = _missive()
    recipient = MissiveRecipientEmail.objects.create(missive=missive, name="Ada", email="ada@example.com")
    page = client.get(reverse("admin:django_pymissive_missive_change", args=[missive.pk]))
    assert page.status_code == 200
    assert reverse("admin:django_pymissive_missiverecipient_change", args=[recipient.pk]).encode() in page.content
    assert b"missiverecipientemail_change" not in page.content


def test_download_proof_missing_params_returns_400():
    """The 400 guard used to raise UnboundLocalError: ``_`` was shadowed later in the body."""
    missive_admin = admin.site._registry[Missive]
    missive = _missive()

    response = missive_admin.download_proof(_superuser_request(method="post"), str(missive.pk))

    assert response.status_code == 400
