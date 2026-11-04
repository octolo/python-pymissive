from ..models.scheduler import MissiveScheduledCampaign


def run_campaign(campaign_id):
    # Fetch by id only; run_with_tracking() performs the atomic send_date
    # claim and returns early if the run was already started by another worker.
    scheduled = MissiveScheduledCampaign.objects.get(id=campaign_id)
    scheduled.run_with_tracking()


def force_release_run(scheduled_id, reason=""):
    """Force-release a run through any configured task backend."""
    scheduled = MissiveScheduledCampaign.objects.get(id=scheduled_id)
    return scheduled.force_release(reason)


def enqueue_force_release_run(scheduled_id, reason=""):
    """Enqueue :func:`force_release_run` on the configured backend."""
    from . import get_task_backend

    get_task_backend().enqueue(force_release_run, str(scheduled_id), reason)
