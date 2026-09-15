"""Duplicate ``external_id`` values are legitimate, so lookups must stay deterministic.

``retrieve_from_provider`` creates a second row with the same provider id on
purpose, and a dry-run resend reuses ``dry-run:<thread_id>``. A plain ``.get()``
raised ``MultipleObjectsReturned``, which ``handle_events`` swallowed — the
webhook event was silently lost.
"""

from __future__ import annotations

import pytest

from django_pymissive.models.choices import MissiveStatus, MissiveThreadType, MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "status": MissiveStatus.DRAFT,
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def _set_created_at(missive, when):
    Missive.objects.filter(pk=missive.pk).update(created_at=when)


def test_duplicate_external_id_resolves_to_the_live_attempt():
    archived = _missive(external_id="dup", thread_type=MissiveThreadType.HISTORY)
    live = _missive(external_id="dup", thread_type=MissiveThreadType.MISSIVE)

    assert Missive.objects.filter(external_id="dup").count() == 2
    assert Missive.objects.get_by_external_id("dup").pk == live.pk
    assert Missive.objects.get_by_external_id("dup").pk != archived.pk


def test_without_a_live_attempt_the_newest_row_wins():
    older = _missive(external_id="dup", thread_type=MissiveThreadType.HISTORY)
    newer = _missive(external_id="dup", thread_type=MissiveThreadType.HISTORY)
    _set_created_at(older, "2026-01-01T00:00:00+00:00")
    _set_created_at(newer, "2026-06-01T00:00:00+00:00")

    assert Missive.objects.get_by_external_id("dup").pk == newer.pk


def test_several_live_attempts_still_resolve_to_one_row():
    """The dry-run resend case: two MISSIVE rows sharing ``dry-run:<thread_id>``."""
    first = _missive(external_id="dry-run:x", thread_type=MissiveThreadType.MISSIVE)
    second = _missive(external_id="dry-run:x", thread_type=MissiveThreadType.MISSIVE)
    _set_created_at(first, "2026-01-01T00:00:00+00:00")
    _set_created_at(second, "2026-06-01T00:00:00+00:00")

    assert Missive.objects.get_by_external_id("dry-run:x").pk == second.pk


def test_unknown_and_empty_external_ids_resolve_to_none():
    _missive(external_id="known")

    assert Missive.objects.get_by_external_id("missing") is None
    assert Missive.objects.get_by_external_id(None) is None
    assert Missive.objects.get_by_external_id("") is None


def test_single_row_lookup_is_unchanged():
    missive = _missive(external_id="solo", thread_type=MissiveThreadType.MISSIVE)

    assert Missive.objects.get_by_external_id("solo").pk == missive.pk


def test_an_archived_only_id_is_still_found():
    """Regression guard: scoping to live attempts must not hide resent missives."""
    archived = _missive(external_id="old", thread_type=MissiveThreadType.HISTORY)

    assert Missive.objects.get_by_external_id("old").pk == archived.pk
