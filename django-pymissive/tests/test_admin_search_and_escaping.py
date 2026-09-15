"""Admin search fields resolve, related-object labels are escaped, and proof download validates."""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory

from django_pymissive.admin.related_object import MissiveRelatedObjectAdmin
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.models.related_object import MissiveRelatedObject

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
    request.user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
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
            queryset, _duplicates = model_admin.get_search_results(
                _request(q="x"), model._default_manager.all(), "x"
            )
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
    MissiveRelatedObject.objects.filter(pk=related.pk).update(
        object_str='<img src=x onerror=alert(1)>'
    )
    related.refresh_from_db()

    rendered = MissiveRelatedObjectAdmin(
        MissiveRelatedObject, admin.site
    ).object_url_link_display(related)

    assert "<img" not in rendered
    assert "&lt;img" in rendered


def test_download_proof_missing_params_returns_400():
    """The 400 guard used to raise UnboundLocalError: ``_`` was shadowed later in the body."""
    missive_admin = admin.site._registry[Missive]
    missive = _missive()

    response = missive_admin.download_proof(
        _superuser_request(method="post"), str(missive.pk)
    )

    assert response.status_code == 400
