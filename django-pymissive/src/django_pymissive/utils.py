"""Utility functions for django_pymissive."""

from urllib.parse import urlparse

from django.conf import settings


def recalculate_attachment_priorities(missive_id=None, campaign_id=None):
    """
    Reassign sequential priorities (1, 2, 3...) for attachments of a missive or campaign.
    Use after inline save or when priority changed programmatically.
    """
    if not missive_id and not campaign_id:
        return
    from .models.attachment import MissiveBaseAttachment

    qs = MissiveBaseAttachment.objects
    if missive_id:
        qs = qs.filter(missive_id=missive_id)
    else:
        qs = qs.filter(campaign_id=campaign_id)
    siblings = list(qs.order_by("priority", "id"))
    to_update = []
    for i, att in enumerate(siblings, start=1):
        if att.priority != i:
            att.priority = i
            to_update.append(att)
    if to_update:
        MissiveBaseAttachment.objects.bulk_update(to_update, ["priority"])


def get_default_domain():
    """Return default domain (host) from settings or localhost:8000.
    If setting is a full URL, extracts the netloc for use in webhook domain field.
    """
    domain = (
        getattr(settings, "MISSIVE_DOMAIN", None)
        or getattr(settings, "DOMAIN", None)
        or "localhost:8000"
    )
    domain = str(domain).strip().rstrip("/")
    if domain.startswith(("http://", "https://")):
        parsed = urlparse(domain)
        return parsed.netloc or domain
    return domain


def get_default_scheme():
    """Return default scheme from settings (MISSIVE_SCHEME, SCHEME) or http.
    If domain setting is a full URL, extracts scheme from it.
    """
    scheme = getattr(settings, "MISSIVE_SCHEME", None) or getattr(settings, "SCHEME", None)
    if scheme:
        return str(scheme).replace("://", "")
    domain = getattr(settings, "MISSIVE_DOMAIN", None) or getattr(settings, "DOMAIN", None)
    if domain and str(domain).strip().lower().startswith("https://"):
        return "https"
    return "http"


def get_base_url(domain=None, scheme=None, trailing_slash=True):
    """
    Build base URL from domain and scheme.
    Defaults: domain=localhost:8000, scheme=http.
    Returns e.g. http://localhost:8000/ (with trailing_slash) or http://localhost:8000.
    """
    domain = domain or get_default_domain()
    scheme = scheme or get_default_scheme()
    scheme = str(scheme).replace("://", "")
    domain = str(domain).strip().rstrip("/")
    if domain.startswith(("http://", "https://")):
        base = domain.rstrip("/")
    else:
        base = f"{scheme}://{domain}"
    return f"{base}/" if trailing_slash else base
