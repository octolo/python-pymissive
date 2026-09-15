"""Instantiate every shipped provider and call its normalizers.

``providers/todo/`` is backlog and is not imported. A missing extra (discord,
boto3) must not prevent instantiation: those imports stay lazy.
"""

from __future__ import annotations

import importlib

import pytest

SHIPPED = (
    ("pymissive.providers.brevo", "BrevoAPIProvider"),
    ("pymissive.providers.scaleway", "ScalewayProvider"),
    ("pymissive.providers.maileva", "MailevaProvider"),
    ("pymissive.providers.partner", "PartnerProvider"),
    ("pymissive.providers.slack", "SlackProvider"),
    ("pymissive.providers.teams", "TeamsProvider"),
    ("pymissive.providers.discord", "DiscordProvider"),
    ("pymissive.providers.hand_delivery", "HandDeliveryProvider"),
)


def _load(module_name: str, class_name: str):
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


@pytest.mark.parametrize(("module_name", "class_name"), SHIPPED)
def test_shipped_provider_instantiates_and_normalizes(module_name, class_name):
    cls = _load(module_name, class_name)
    provider = cls()
    payload = {"event": "__missing__", "id": "wh-1", "webhook_id": "wh-1"}

    assert isinstance(provider.get_normalize_event(payload), str)
    webhook_id = provider.get_normalize_webhook_id(payload)
    assert webhook_id is None or isinstance(webhook_id, str)
    if hasattr(provider, "get_normalize_external_id"):
        provider.get_normalize_external_id(payload)
    assert isinstance(provider.get_brands(), list)


def test_todo_is_not_among_the_shipped_provider_modules():
    """``todo/`` is a backlog folder, not a discoverable provider."""
    import pkgutil

    import pymissive.providers as providers_pkg

    names = {module.name for module in pkgutil.iter_modules(providers_pkg.__path__)}
    shipped_modules = {module for module, _cls in SHIPPED}
    discovered = {
        f"pymissive.providers.{name}"
        for name in names
        if name not in {"base", "todo"}
    }
    assert discovered == shipped_modules
