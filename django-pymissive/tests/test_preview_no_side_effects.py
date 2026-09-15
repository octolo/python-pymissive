"""The public "view in browser" preview must not write to the database.

``PreviewView`` is unauthenticated by design — ``add_preview_browser`` embeds its
URL in outgoing emails. It used to call ``ensure_first_document()``, so every
recipient opening the link deleted and re-rendered the first-document PDF of an
already sent postal missive.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from django_pymissive.models import MissiveRecipientAddress
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _postal_missive() -> Missive:
    missive = Missive.objects.create(
        missive_type=MissiveType.LRE,
        subject="LRAR",
        status=MissiveStatus.SUCCESS,
        external_id="mv-sent-1",
        sender_name="Octolo",
        sender_address={
            "address_line1": "1 rue de la Paix",
            "postal_code": "75002",
            "city": "Paris",
            "country": "France",
        },
    )
    MissiveRecipientAddress.objects.create(
        missive=missive,
        name="Alice Martin",
        address={
            "address_line1": "10 rue Example",
            "postal_code": "75001",
            "city": "Paris",
            "country": "France",
        },
    )
    return missive


def test_anonymous_preview_does_not_regenerate_the_first_document():
    missive = _postal_missive()
    url = reverse("django_pymissive:preview", args=["missive", missive.pk])

    # A postal missive redirects to the per-recipient preview route.
    with patch.object(Missive, "ensure_first_document") as ensure, patch.object(
        Missive, "generate_first_document"
    ) as generate:
        response = Client().get(url, follow=True)

    assert response.status_code == 200
    ensure.assert_not_called()
    generate.assert_not_called()


def test_preview_stays_reachable_without_authentication():
    """Recipients receive this link by email; protecting it would break the feature."""
    missive = _postal_missive()
    url = reverse("django_pymissive:preview", args=["missive", missive.pk])

    response = Client().get(url, follow=True)

    assert response.status_code == 200
    # Not a login redirect: it stays inside the preview routes.
    assert all("login" not in step[0] for step in response.redirect_chain)
