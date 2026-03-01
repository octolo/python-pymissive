from django.conf import settings


def get_campaign_backend():
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
