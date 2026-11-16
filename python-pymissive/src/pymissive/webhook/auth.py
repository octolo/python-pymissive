"""Generic inbound webhook authentication.

The HTTP gate accepts Bearer authentication, a Basic-auth password, or a URL
path token. Providers remain responsible for their outbound API payloads.
"""

from __future__ import annotations

import base64
import hmac


def get_webhook_secret(provider) -> str:
    """Read ``WEBHOOK_SECRET`` from a provider instance. Empty if unset."""
    getter = getattr(provider, "_get_config_or_env", None)
    if getter is None:
        return ""
    raw = getter("WEBHOOK_SECRET", "") or ""
    return str(raw).strip()


def authorization_matches(
    secret: str,
    *,
    authorization: str = "",
    url_token: str = "",
) -> bool:
    """True when Bearer, Basic password, or path token equals ``secret``."""
    if not secret:
        return True
    if url_token and _digest_equal(url_token, secret):
        return True
    scheme, _, rest = (authorization or "").strip().partition(" ")
    if not rest:
        return False
    kind = scheme.lower()
    if kind == "bearer":
        return _digest_equal(rest.strip(), secret)
    if kind == "basic":
        return _basic_password_matches(rest.strip(), secret)
    return False


def verify_inbound_webhook(
    provider,
    *,
    authorization: str = "",
    url_token: str = "",
) -> bool:
    """Opt-in check. No secret → accept. Secret set → require a matching proof."""
    secret = get_webhook_secret(provider)
    if not secret:
        return True
    return authorization_matches(secret, authorization=authorization, url_token=url_token)


def _digest_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _basic_password_matches(b64_credentials: str, secret: str) -> bool:
    try:
        decoded = base64.b64decode(b64_credentials, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    _login, separator, password = decoded.partition(":")
    if not separator:
        return False
    return _digest_equal(password, secret)
