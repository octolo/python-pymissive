"""A successful Maileva submit is ``request``, including 201/202."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from pymissive.providers.maileva import MailevaProvider


@pytest.mark.parametrize("status_code", [200, 201, 202])
def test_send_registered_letter_success_is_request_for_any_2xx(status_code):
    provider = MailevaProvider.__new__(MailevaProvider)
    provider._stage_postal_before_submit = lambda **kwargs: ("ext-1", [], [])
    provider.get_endpoint = lambda name, **kwargs: "%s/submit"
    response = Mock(status_code=status_code, text="", ok=True)
    response.raise_for_status = Mock()

    with (
        patch.object(provider, "_request", return_value=response),
        patch("pymissive.providers.maileva.is_disable_send", return_value=False),
    ):
        data = provider.send_registered_letter()

    assert data["event"] == "request"
    assert data["code"] == status_code
    assert data["id"] == "ext-1"
