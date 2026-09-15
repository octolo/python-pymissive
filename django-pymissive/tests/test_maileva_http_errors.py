"""Maileva HTTP errors keep a debug handle without echoing the sending payload."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
import requests

from pymissive.providers.maileva import MailevaProvider, _compact_http_error_detail


def test_compact_detail_keeps_field_errors_not_recipients():
    body = json.dumps(
        {
            "code": "VALIDATION_ERROR",
            "message": "Invalid recipient",
            "recipients": [
                {"name": "Jean Dupont", "address_line_6": "75001 PARIS"},
            ],
            "errors": [
                {"field": "address_line_6", "message": "invalid postal code"},
            ],
        }
    )
    summary = _compact_http_error_detail(body)
    assert "VALIDATION_ERROR" in summary
    assert "address_line_6" in summary
    assert "invalid postal code" in summary
    assert "Jean Dupont" not in summary
    assert "75001" not in summary


def test_compact_detail_ignores_html():
    assert _compact_http_error_detail("<html>Jean Dupont 12 rue X</html>") == ""


def test_raise_for_response_keeps_body_on_exception_not_in_message():
    payload = {
        "code": "VALIDATION_ERROR",
        "message": "Invalid recipient",
        "name": "Jean Dupont",
        "address_line_6": "12 rue de la Paix 75002 PARIS",
        "errors": [{"field": "address_line_6", "message": "invalid postal code"}],
    }
    response = Mock()
    response.status_code = 400
    response.reason = "Bad Request"
    response.text = json.dumps(payload)
    response.raise_for_status.side_effect = requests.HTTPError(
        "400 Client Error", response=response
    )

    provider = MailevaProvider.__new__(MailevaProvider)
    with pytest.raises(requests.HTTPError) as excinfo:
        provider._raise_for_response(response, "Maileva create sending failed")

    message = str(excinfo.value)
    assert "Maileva create sending failed: 400 Bad Request" in message
    assert "VALIDATION_ERROR" in message
    assert "address_line_6" in message
    assert "Jean Dupont" not in message
    assert "12 rue de la Paix" not in message
    assert excinfo.value.response is response
    assert "Jean Dupont" in excinfo.value.response.text
