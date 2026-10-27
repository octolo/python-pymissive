"""Random webhooks for missives already sent through the fake provider.

One function, two callers:

- ``manage.py fake`` runs it in this process
- the missive admin view enqueues it on the configured task backend

Each call posts one JSON body per missive to ``/webhook/fake/<missive_type>/``.
The request stays inside Django (the webhook view, on that URL) so a dev
server does not have to call itself. The event is chosen at random among
delivered, failed, still in progress, and cancelled. ``set_status`` then
moves the missive.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import timezone as dt_timezone

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from pymissive.providers.fake import FakeProvider
from pymissive.utils import is_fake_provider_allowed

from .models.choices import TERMINAL_STATUSES, MissiveThreadType, sent_missive_q
from .models.missive import Missive
from .utils import build_webhook_url, get_base_url

logger = logging.getLogger(__name__)

PROVIDER = FakeProvider.name

#: Canonical events the webhook may report. ``error`` is a failed event, so
#: the missive status becomes ``failed``. ``cancelled`` is terminal.
OUTCOMES = (
    "delivered",
    "opened",
    "clicked",
    "failed",
    "error",
    "hard_bounce",
    "rejected",
    "undelivered",
    "sent",
    "accepted",
    "processing",
    "cancelled",
)


class FakeProviderDisabled(RuntimeError):
    """``PYMISSIVE_ALLOW_FAKE_PROVIDER`` is off."""


def ensure_fake_provider_allowed() -> None:
    if not is_fake_provider_allowed():
        raise FakeProviderDisabled(_("Fake provider is disabled: set PYMISSIVE_ALLOW_FAKE_PROVIDER to use it."))


def sent_fake_missives():
    """Missives the fake provider already accepted, still open to a webhook."""
    return (
        Missive.objects.filter(
            sent_missive_q(),
            provider=PROVIDER,
            thread_type=MissiveThreadType.MISSIVE,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id="")
        .exclude(status__in=TERMINAL_STATUSES)
        .order_by("created_at", "pk")
    )


def webhook_path(missive_type: str) -> str:
    return reverse(
        "django_pymissive:missive_webhook",
        kwargs={"provider": PROVIDER, "missive_type": missive_type},
    )


def webhook_url(missive_type: str) -> str:
    return build_webhook_url(get_base_url(trailing_slash=False), PROVIDER, missive_type)


def _payload(missive, rng: random.Random) -> list[dict]:
    when = timezone.now().astimezone(dt_timezone.utc).isoformat()
    recipients = list(missive.to_missiverecipient.all()) or [None]
    events = []
    for recipient in recipients:
        event = rng.choice(OUTCOMES)
        item = {
            "external_id": missive.external_id,
            "event": event,
            "occurred_at": when,
            "reason": f"Fake webhook ({event})",
        }
        if recipient is not None:
            item["recipient"] = {"id": recipient.pk}
        events.append(item)
    return events


def post_webhook(missive_type: str, payload: list[dict]) -> int:
    """POST ``payload`` to the fake webhook URL and return the status code."""
    from django.test import Client

    headers: dict[str, str] = {}
    secret = FakeProvider().get_webhook_secret()
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    response = Client().post(
        webhook_path(missive_type),
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )
    return response.status_code


def run_fake_webhooks(*, limit: int | None = None, seed: int | None = None) -> dict:
    """Post one random webhook per sent fake missive.

    ``limit`` keeps the first missives (oldest pk). ``seed`` makes the
    drawn events repeatable.
    """
    ensure_fake_provider_allowed()
    rng = random.Random(seed)  # nosec B311
    missives = sent_fake_missives().prefetch_related("to_missiverecipient")
    if limit is not None:
        missives = missives[: int(limit)]
    posted = 0
    failed = 0
    results = []
    for missive in missives:
        payload = _payload(missive, rng)
        status_code = post_webhook(missive.missive_type, payload)
        events = [item["event"] for item in payload]
        row = {
            "missive_id": str(missive.pk),
            "url": webhook_url(missive.missive_type),
            "events": events,
            "status_code": status_code,
        }
        results.append(row)
        if status_code == 200:
            posted += 1
            logger.info("fake webhook %s", row)
        else:
            failed += 1
            logger.warning("fake webhook failed %s", row)
    return {"posted": posted, "failed": failed, "results": results}


def delay_fake_webhooks(*, limit: int | None = None, seed: int | None = None) -> None:
    """Enqueue :func:`run_fake_webhooks` on the configured task backend."""
    from .task import get_task_backend

    ensure_fake_provider_allowed()
    get_task_backend().enqueue(run_fake_webhooks, limit=limit, seed=seed)
