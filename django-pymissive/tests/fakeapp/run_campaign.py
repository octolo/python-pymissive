"""Fake campaign runner for testing task_object delegation and external_task_backend."""

from django_pymissive.processors.body._base import get_default_body_processors


def run_fakeapp_campaign(scheduled_id, **kwargs):
    """Fakeapp runner — receives scheduled_id, fetches fresh state, applies hook then sends.

    Uses process_missives() for best-effort sending: a failing missive is moved
    to ERROR and the batch continues.
    """
    from django_pymissive.models.scheduler import MissiveScheduledCampaign
    scheduled = MissiveScheduledCampaign.objects.get(id=scheduled_id)
    processors = get_default_body_processors() + ["tests.fakeapp.hook.add_fake_text"]

    def _send(missive):
        missive.body_processors = processors
        missive.save(update_fields=["body_processors"])
        missive.send_missive()

    scheduled.process_missives(_send)
