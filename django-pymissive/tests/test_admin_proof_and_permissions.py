"""Proof download never fetches a caller-supplied URL, and change permission is Django's.

``download_proof`` used to forward ``?url=`` straight to the provider HTTP
client, and ``has_change_permission`` returned an unconditional ``True``, which
gave every staff account write access to every missive — sending included.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db

PROOFS = [{"filename": "proof.pdf", "url": "https://provider.example/proofs/1"}]


def _missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "status": MissiveStatus.DRAFT,
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def _staff(username, *codenames):
    user = get_user_model().objects.create_user(
        username=username, password="x", is_staff=True
    )
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    return get_user_model().objects.get(pk=user.pk)


def _request(user, method="get", **params):
    request = getattr(RequestFactory(), method)("/", params)
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _unwrapped(model_admin, name):
    """``setup_boost_views`` shadows boost views on the instance; the class keeps the method."""
    return getattr(type(model_admin), name)


def test_download_proof_ignores_a_forged_url():
    missive = _missive()
    missive_admin = admin.site._registry[Missive]
    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return b"%PDF-1.4"

    with patch.object(Missive, "get_proofs", return_value=PROOFS), patch.object(
        Missive, "download_proof", side_effect=_capture
    ), patch.object(Missive, "get_serialized_data", return_value={}):
        response = missive_admin.download_proof(
            _request(
                _staff("attacker", "view_missive", "change_missive"),
                method="post",
                filename="proof.pdf",
                url="http://169.254.169.254/latest/meta-data/",
            ),
            str(missive.pk),
        )

    assert response.status_code == 200
    assert captured["url"] == "https://provider.example/proofs/1"


def test_download_proof_rejects_an_unlisted_filename():
    missive = _missive()
    missive_admin = admin.site._registry[Missive]

    with patch.object(Missive, "get_proofs", return_value=PROOFS), patch.object(
        Missive, "download_proof"
    ) as download:
        response = missive_admin.download_proof(
            _request(
                _staff("prober", "view_missive", "change_missive"),
                method="post",
                filename="../../secret.pdf",
            ),
            str(missive.pk),
        )

    assert response.status_code == 404
    download.assert_not_called()


def test_download_proof_without_a_filename_returns_400():
    missive = _missive()
    missive_admin = admin.site._registry[Missive]

    response = missive_admin.download_proof(
        _request(_staff("empty", "view_missive", "change_missive"), method="post"),
        str(missive.pk),
    )

    assert response.status_code == 400


def test_download_proof_rejects_get():
    """A GET (img, prefetch, CSRF) must not call the provider."""
    missive = _missive()
    missive_admin = admin.site._registry[Missive]

    with patch.object(Missive, "get_proofs") as get_proofs, patch.object(
        Missive, "download_proof"
    ) as download:
        response = missive_admin.download_proof(
            _request(
                _staff("getter", "view_missive"),
                filename="proof.pdf",
            ),
            str(missive.pk),
        )

    assert response.status_code == 405
    get_proofs.assert_not_called()
    download.assert_not_called()


def test_save_proofs_get_does_not_call_the_provider():
    missive = _missive()
    missive_admin = admin.site._registry[Missive]
    editor = _request(_staff("editor-proofs", "view_missive", "change_missive"))

    with patch.object(Missive, "get_proofs") as get_proofs, patch.object(
        Missive, "download_proof"
    ) as download:
        payload = _unwrapped(missive_admin, "save_proofs")(
            missive_admin, editor, missive
        )

    assert "confirm" in payload
    get_proofs.assert_not_called()
    download.assert_not_called()


def test_staff_without_change_permission_cannot_change_a_missive():
    missive = _missive()
    missive_admin = admin.site._registry[Missive]

    viewer = _request(_staff("viewer", "view_missive"))

    assert missive_admin.has_change_permission(viewer, missive) is False


def test_staff_with_change_permission_can_change_a_missive():
    missive = _missive()
    missive_admin = admin.site._registry[Missive]

    editor = _request(_staff("editor", "view_missive", "change_missive"))

    assert missive_admin.has_change_permission(editor, missive) is True


# Every action that mutates data or spends provider credit. Navigation views
# (history, conversation, preview) stay available with view permission only.
MUTATING_HOOKS = [
    "has_prepare_missive_permission",
    "has_resend_missive_permission",
    "has_send_missive_permission",
    "has_cancel_missive_permission",
    "has_delete_missive_permission",
    "has_refresh_from_provider_permission",
    "has_retrieve_missive_permission",
    "has_retrieve_tracking_numbers_permission",
    "has_duplicate_missive_permission",
    "has_set_billed_permission",
    "has_get_billings_permission",
    "has_handle_proofs_permission",
    "has_download_proof_permission",
    "has_save_proofs_permission",
]


@pytest.mark.parametrize("hook", MUTATING_HOOKS)
def test_mutating_action_hooks_refuse_a_view_only_account(hook):
    missive = _missive(external_id="mv-1")
    missive_admin = admin.site._registry[Missive]

    viewer = _request(_staff(f"viewer-{hook}", "view_missive"))

    assert getattr(missive_admin, hook)(viewer, missive) is False


def test_navigation_actions_stay_open_to_a_view_only_account():
    """These only redirect to a filtered changelist; they change nothing."""
    missive = _missive()
    missive_admin = admin.site._registry[Missive]
    viewer = _request(_staff("viewer-nav", "view_missive"))

    with patch.object(Missive, "count_history", 2, create=True):
        assert missive_admin.has_handle_history_permission(viewer, missive) is True


def test_the_send_confirm_view_refuses_a_view_only_account():
    """The button is hidden, but the boost view URL is reachable on its own.

    Goes through the generated wrapper, which only checks view permission — the
    guard has to live in the view body.
    """
    missive = _missive()
    missive_admin = admin.site._registry[Missive]
    viewer = _request(
        _staff("viewer-send", "view_missive"), method="post", action="confirm"
    )

    with patch.object(Missive, "send_missive") as send:
        with pytest.raises(PermissionDenied):
            missive_admin.send_missive(viewer, str(missive.pk))

    send.assert_not_called()


def test_the_send_confirm_view_accepts_an_editor():
    missive = _missive()
    missive_admin = admin.site._registry[Missive]
    editor = _request(_staff("editor-send", "view_missive", "change_missive"))

    payload = _unwrapped(missive_admin, "send_missive")(missive_admin, editor, missive)

    assert "confirm" in payload


def test_the_campaign_start_view_refuses_a_view_only_account():
    campaign = MissiveCampaign.objects.create(subject="Promo")
    campaign_admin = admin.site._registry[MissiveCampaign]
    viewer = _request(_staff("viewer-campaign", "view_missivecampaign"))

    with patch.object(MissiveCampaign, "start_campaign") as start:
        with pytest.raises(PermissionDenied):
            _unwrapped(campaign_admin, "start_campaign")(
                campaign_admin, viewer, campaign, confirmed=True
            )

    start.assert_not_called()


def test_can_proofs_is_false_without_a_provider_service():
    missive = _missive(external_id="ext-1")
    assert missive.can_proofs() is False


def test_can_proofs_requires_an_external_id_and_the_retrieve_service():
    missive = _missive(external_id="ext-1")
    with (
        patch.object(Missive, "has_service", return_value=True) as has_service,
        patch("django_pymissive.models.missive.is_dry_run", return_value=False),
    ):
        assert missive.can_proofs() is True
    has_service.assert_called_with("retrieve_proofs")

    missive.external_id = ""
    with (
        patch.object(Missive, "has_service", return_value=True),
        patch("django_pymissive.models.missive.is_dry_run", return_value=False),
    ):
        assert missive.can_proofs() is False


def test_get_proofs_short_circuits_when_can_proofs_is_false():
    missive = _missive()
    with patch.object(Missive, "can_proofs", return_value=False):
        assert missive.get_proofs() == []
        assert missive.download_proof(url="https://example/proof") is None


def test_a_locked_missive_rejects_a_post_even_with_change_permission():
    """An ``external_id`` means the provider already has it; it must stay frozen."""
    missive = _missive(external_id="mv-1")
    missive_admin = admin.site._registry[Missive]

    editor = _request(_staff("editor", "view_missive", "change_missive"), method="post")

    assert missive_admin.has_change_permission(editor, missive) is False
