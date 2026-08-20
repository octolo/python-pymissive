from django.conf import settings


def get_task_backend():
    """Return the backend selected by ``CAMPAIGN_TASK_BACKEND``."""
    backend = getattr(settings, "CAMPAIGN_TASK_BACKEND", "sync")

    if backend == "celery":
        from .celery import CeleryBackend

        return CeleryBackend()
    elif backend == "rq":
        from .django_rq import RQBackend

        return RQBackend()
    elif backend == "thread":
        from .thread import ThreadBackend

        return ThreadBackend()
    else:
        from .sync import SyncBackend

        return SyncBackend()


get_campaign_backend = get_task_backend
