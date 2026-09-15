"""Provider mixins keep declared brands and give each instance its own attachments list."""

from __future__ import annotations

import pytest

from pymissive.providers.brevo import BrevoAPIProvider
from pymissive.providers.maileva import MailevaProvider
from pymissive.providers.slack import SlackProvider
from pymissive.providers.teams import TeamsProvider


@pytest.mark.parametrize(
    ("provider_class", "expected"),
    [
        (BrevoAPIProvider, ["WhatsApp"]),
        (SlackProvider, ["slack"]),
        (TeamsProvider, ["teams"]),
        (MailevaProvider, []),
    ],
)
def test_declared_brands_survive_class_creation(provider_class, expected):
    """``BrandedMixin.__init_subclass__`` ran after the class body and reset ``brands`` to []."""
    assert provider_class.brands == expected
    assert provider_class().get_brands() == expected


def test_each_instance_gets_its_own_attachments_list():
    first = BrevoAPIProvider()
    second = BrevoAPIProvider()

    first.attachments.append({"name": "leak.pdf"})

    assert second.get_attachments() == []
    assert first.get_attachments() == [{"name": "leak.pdf"}]
