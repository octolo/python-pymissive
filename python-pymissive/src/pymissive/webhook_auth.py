"""Inbound webhook proof and outbound registration payloads.

One ``WEBHOOK_SECRET`` per provider. The HTTP gate accepts any of:

- ``Authorization: Bearer <secret>`` (Brevo)
- ``Authorization: Basic …`` whose password is the secret (Maileva)
- URL path token equal to the secret (Scaleway SNS, no custom headers)

Each provider maps that same secret onto its own create/update API.
"""

from __future__ import annotations

import base64
import hmac

#: Default ``authentication.basic.login`` (Maileva). Overridable via
#: ``WEBHOOK_BASIC_LOGIN``. Only the password is checked inbound.
WEBHOOK_BASIC_LOGIN = "pymissive"


def get_webhook_secret(provider) -> str:
    """Read ``WEBHOOK_SECRET`` from a provider instance. Empty if unset."""
    getter = getattr(provider, "_get_config_or_env", None)
    if getter is None:
        return ""
    raw = getter("WEBHOOK_SECRET", "") or ""
    return str(raw).strip()


def get_webhook_basic_login(provider) -> str:
    """Read ``WEBHOOK_BASIC_LOGIN``, default ``pymissive``."""
    getter = getattr(provider, "_get_config_or_env", None)
    if getter is None:
        return WEBHOOK_BASIC_LOGIN
    raw = getter("WEBHOOK_BASIC_LOGIN", WEBHOOK_BASIC_LOGIN) or WEBHOOK_BASIC_LOGIN
    return str(raw).strip() or WEBHOOK_BASIC_LOGIN


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
    return authorization_matches(
        secret, authorization=authorization, url_token=url_token
    )


def maileva_subscription_authentication(
    secret: str, login: str = WEBHOOK_BASIC_LOGIN
) -> dict:
    """Body fragment for Maileva ``POST/PATCH /subscriptions``.

    See notification_center v2 ``authentication.basic``
    (https://www.maileva.com/catalogue-api/notifications-webhooks/).
    """
    return {
        "basic": {
            "login": login or WEBHOOK_BASIC_LOGIN,
            "password": secret,
        }
    }


def brevo_webhook_auth(secret: str) -> dict:
    """``auth`` object for Brevo create/update webhook (Bearer)."""
    return {"type": "bearer", "token": secret}


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
