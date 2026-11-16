"""URL and webhook URL helpers."""

from urllib.parse import urlparse

from django.conf import settings
from django.urls import reverse


def get_default_domain():
    """Return default domain (host) from settings or localhost:8000.
    If setting is a full URL, extracts the netloc for use in webhook domain field.
    """
    domain = getattr(settings, "PYMISSIVE_DOMAIN", None) or getattr(settings, "DOMAIN", None) or "localhost:8000"
    domain = str(domain).strip().rstrip("/")
    if domain.startswith(("http://", "https://")):
        parsed = urlparse(domain)
        return parsed.netloc or domain
    return domain


def get_default_scheme():
    """Return default scheme from settings (PYMISSIVE_SCHEME, SCHEME) or http.
    If domain setting is a full URL, extracts scheme from it.
    """
    scheme = getattr(settings, "PYMISSIVE_SCHEME", None) or getattr(settings, "SCHEME", None)
    if scheme:
        return str(scheme).replace("://", "")
    domain = getattr(settings, "PYMISSIVE_DOMAIN", None) or getattr(settings, "DOMAIN", None)
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


def build_webhook_url(domain: str, provider_name: str, missive_type: str, token: str | None = None) -> str:
    """Build full webhook URL from domain, provider and missive type.

    ``token`` is the path secret for providers that cannot send an
    Authorization header.
    """
    domain = (domain or "").rstrip("/")
    kwargs = {"provider": provider_name, "missive_type": missive_type}
    name = "django_pymissive:missive_webhook"
    if token:
        kwargs["token"] = token
        name = "django_pymissive:missive_webhook_token"
    path = reverse(name, kwargs=kwargs)
    return f"{domain}{path}"


def webhook_url_token_for(provider) -> str:
    """Path token when the provider requires one and a secret is set."""
    inner = getattr(provider, "_provider", provider)
    uses_token = getattr(inner, "webhook_uses_url_token", None)
    if not callable(uses_token) or not uses_token():
        return ""
    getter = getattr(inner, "get_webhook_secret", None)
    if not callable(getter):
        return ""
    return getter() or ""
