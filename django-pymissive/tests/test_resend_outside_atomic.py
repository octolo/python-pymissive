"""``resend_missive`` must not wrap the provider send in ``atomic()``."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from django_pymissive.models.choices import (
    MissiveEventType,
    MissiveStatus,
    MissiveThreadType,
    MissiveType,
)
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def test_resend_keeps_history_and_external_id_if_post_send_fails():
    """A failure after the provider accepted the send must not undo the resend."""
    original = Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        status=MissiveStatus.SUCCESS,
        subject="Hello",
        external_id="old-1",
    )

    with (
        patch.object(Missive, "can_resend", return_value=True),
        patch.object(Missive, "can_send", return_value=True),
        patch.object(Missive, "get_serialized_data", return_value={}),
        patch.object(Missive, "set_locally_ifnull"),
        patch.object(
            Missive, "call_provider_service", return_value={"external_id": "new-1"}
        ),
        patch(
            "django_pymissive.models.missive.missive_post_send.send",
            side_effect=RuntimeError("after send"),
        ),
    ):
        with pytest.raises(RuntimeError, match="after send"):
            original.resend_missive()

    original.refresh_from_db()
    assert original.thread_type == MissiveThreadType.HISTORY
    clone = Missive.objects.exclude(pk=original.pk).get()
    assert clone.external_id == "new-1"
    assert MissiveEvent.objects.filter(
        missive=clone, event=MissiveEventType.SUBMITTED
    ).exists()
