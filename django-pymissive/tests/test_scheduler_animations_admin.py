"""Scheduler admin renders the communication animations in the page."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _url():
    return reverse("admin:django_pymissive_missivescheduledcampaign_animations")


def _admin_client():
    user = get_user_model().objects.create_superuser(username="admin", email="admin@example.com", password="x")
    client = Client()
    client.force_login(user)
    return client


def test_changelist_links_to_the_animations_view():
    response = _admin_client().get(reverse("admin:django_pymissive_missivescheduledcampaign_changelist"))
    assert response.status_code == 200
    assert _url() in response.content.decode()


def test_progress_json_and_send_animations_follow_the_missive_types():
    from django_pymissive.models import (
        Missive,
        MissiveCampaign,
        MissiveScheduledCampaign,
        MissiveStatus,
    )

    campaign = MissiveCampaign.objects.create(subject="Run")
    run = MissiveScheduledCampaign.objects.create(campaign=campaign)
    Missive.objects.create(
        campaign=campaign,
        scheduler=run,
        missive_type="email",
        subject="Hello",
        status=MissiveStatus.SUCCESS,
    )
    Missive.objects.create(
        campaign=campaign,
        scheduler=run,
        missive_type="sms",
        subject="Hello",
        status=MissiveStatus.DRAFT,
    )
    Missive.objects.create(
        campaign=campaign,
        scheduler=run,
        missive_type="notification",
        subject="Hello",
        status=MissiveStatus.DRAFT,
    )
    client = _admin_client()

    payload = client.get(reverse("admin:django_pymissive_missivescheduledcampaign_progress", args=[run.pk]))
    assert payload["Content-Type"].startswith("application/json")
    by_type = payload.json()["by_type"]
    assert by_type["email"]["sent"] == 1
    assert by_type["sms"]["total"] == 1
    assert "letter" not in by_type

    html = client.get(
        reverse(
            "admin:django_pymissive_missivescheduledcampaign_send_animations",
            args=[run.pk],
        )
    ).content.decode()
    assert '"preset": "email"' in html
    assert '"preset": "sms"' in html
    assert '"preset": "notification"' in html
    assert "frame-email" in html
    assert "frame-sms" in html
    assert "frame-notification" in html
    assert payload.request["PATH_INFO"] in html
    assert 'data-run-status="pending"' in html
    assert "widget.finish({ status, errors: frame.errors })" in html


def test_send_animations_view_says_when_the_run_has_nothing_to_send():
    from django_pymissive.models import MissiveCampaign, MissiveScheduledCampaign

    run = MissiveScheduledCampaign.objects.create(
        campaign=MissiveCampaign.objects.create(subject="Empty"),
    )
    html = (
        _admin_client()
        .get(
            reverse(
                "admin:django_pymissive_missivescheduledcampaign_send_animations",
                args=[run.pk],
            )
        )
        .content.decode()
    )
    assert "Nothing to send on this run." in html
    assert "PymissiveAnimation.mountCard" not in html


def test_animations_view_renders_the_examples_in_the_admin_page():
    response = _admin_client().get(_url())
    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="frame-email"' in html
    assert 'id="frame-voice"' in html
    assert 'id="frame-notification"' in html
    assert 'id="custom-preview"' in html
    assert "View the integration code" in html
    assert "PymissiveAnimation.mountCard" in html
    assert "django_pymissive/css/animations.css" in html
    assert "django_pymissive/js/animation.js" in html
    assert 'id="pymissive-animation-labels"' in html
    assert 'data-finale-status="completed"' in html
    assert 'data-finale-status="errors"' in html
    assert 'data-finale-status="cancelled"' in html
    assert "customWidget.finish" in html
    assert html.index('id="pymissive-animation-labels"') < html.index("django_pymissive/js/animation.js")
    assert "<iframe" not in html.lower()


def test_animation_labels_follow_the_active_language():
    from django.utils import translation

    with translation.override("fr"):
        html = Template("{% load django_pymissive_animations %}{% pymissive_animations_labels %}").render(Context({}))
    assert '"postal.title": "Courrier postal"' in html
    assert '"counter.sentMany": "envoy\\u00e9s"' in html
    assert '"end.sent": "Envoy\\u00e9"' in html
    assert '"end.cancelled": "Annul\\u00e9"' in html


def test_cancel_run_view_cancels_a_running_send_with_a_reason():
    from django.utils import timezone

    from django_pymissive.models import MissiveCampaign, MissiveScheduledCampaign

    run = MissiveScheduledCampaign.objects.create(
        campaign=MissiveCampaign.objects.create(subject="Run"),
        send_date=timezone.now(),
    )
    url = reverse("admin:django_pymissive_missivescheduledcampaign_cancel_run", args=[run.pk])
    client = _admin_client()

    assert client.get(url).status_code == 200
    response = client.post(url, {"cancel_reason": "wrong list"})

    assert response.status_code == 302
    run.refresh_from_db()
    assert run.cancelled_at is not None
    assert run.cancel_reason == "wrong list"


def test_progress_page_passes_the_stopped_label_to_its_script():
    from django.utils import translation

    from django_pymissive.models import MissiveCampaign, MissiveScheduledCampaign

    run = MissiveScheduledCampaign.objects.create(
        campaign=MissiveCampaign.objects.create(subject="Run"),
    )
    url = reverse("django_pymissive:scheduler_progress", args=[run.pk])
    client = _admin_client()

    with translation.override("fr"):
        html = client.get(url, HTTP_ACCEPT_LANGUAGE="fr").content.decode()
    payload = client.get(url, {"format": "json"})

    assert 'data-label-stopped="Mises à jour en direct arrêtées. Rechargez la page."' in html
    assert payload["Content-Type"] == "application/json"
    assert payload.json()["status"] == "pending"


def test_running_send_cannot_be_cancelled_from_the_change_form():
    from django.contrib import admin
    from django.test import RequestFactory
    from django.utils import timezone

    from django_pymissive.models import MissiveCampaign, MissiveScheduledCampaign

    run = MissiveScheduledCampaign.objects.create(
        campaign=MissiveCampaign.objects.create(subject="Run"),
        send_date=timezone.now(),
    )
    request = RequestFactory().get("/")
    request.user = get_user_model().objects.create_superuser(username="admin", email="admin@example.com", password="x")

    readonly = admin.site._registry[MissiveScheduledCampaign].get_readonly_fields(request, run)

    assert {"cancelled_at", "cancel_reason"} <= set(readonly)


def test_scheduler_admin_save_does_not_refresh_worker_heartbeat():
    from datetime import timedelta
    from types import SimpleNamespace

    from django.contrib import admin
    from django.utils import timezone

    from django_pymissive.models import MissiveCampaign, MissiveScheduledCampaign

    run = MissiveScheduledCampaign.objects.create(
        campaign=MissiveCampaign.objects.create(subject="Run"),
    )
    heartbeat = timezone.now() - timedelta(hours=2)
    MissiveScheduledCampaign.objects.filter(pk=run.pk).update(updated_at=heartbeat)
    run.refresh_from_db()
    run.progress_step = 10

    admin.site._registry[MissiveScheduledCampaign].save_model(
        None,
        run,
        SimpleNamespace(changed_data=["progress_step"]),
        change=True,
    )

    run.refresh_from_db()
    assert run.progress_step == 10
    assert run.updated_at == heartbeat


def test_animation_template_tags_load_css_js_and_both():
    html = Template(
        "{% load django_pymissive_animations %}"
        "{% pymissive_animations_css %}{% pymissive_animations_js %}{% pymissive_animations_assets %}"
    ).render(Context({}))
    assert html.count("animations.css") == 2
    assert html.count("/animation.js") == 2
    assert html.count("data-pymissive-animations") == 4
