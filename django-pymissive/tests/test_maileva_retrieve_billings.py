"""Maileva bulk retrieve_billings over a date range."""

from datetime import date
from unittest.mock import patch

from pymissive.providers.maileva import MailevaProvider


def _provider():
    provider = MailevaProvider.__new__(MailevaProvider)
    provider.is_mode_sandbox = lambda: False
    provider.get_endpoint = (
        lambda endpoint, prefix="api": "https://api.maileva.com/billing/v1/recipient_items"
    )
    provider._get_headers = lambda: {}
    return provider


def test_retrieve_billings_paginates_and_maps_user_reference():
    captured = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    first_page = {
        "paging": {"total_results": 101},
        "items": [
            {
                "amount": 1.23,
                "label": "registered letter",
                "user_reference": "sub-1",
                "sending_id": "send-1",
                "recipient_id": "rec-ext",
                "recipient_custom_id": "rec-sub",
            }
        ]
        + [{"amount": 0.1, "label": "pad", "user_reference": f"p-{i}"} for i in range(99)],
    }
    second_page = {
        "paging": {"total_results": 101},
        "items": [
            {
                "amount": 4.56,
                "label": "AR",
                "user_reference": "sub-2",
                "sending_id": "send-2",
                "recipient_id": "rec-2",
            }
        ],
    }
    pages = [first_page, second_page]

    def fake_request(method, url, headers=None, timeout=None, params=None, **kwargs):
        captured.append({"url": url, "params": params})
        return FakeResponse(pages[len(captured) - 1])

    with patch("pymissive.providers.maileva.requests.request", fake_request):
        result = MailevaProvider.retrieve_billings(
            _provider(), date(2026, 8, 1), date(2026, 8, 31)
        )

    assert len(result["billings"]) == 101
    first = result["billings"][0]
    assert first["external_id"] == "send-1"
    assert first["substitute_id"] == "sub-1"
    assert first["billing_amount"] == 1.23
    assert first["recipient"] == {
        "id": "rec-sub",
        "substitute_id": "rec-sub",
        "external_id": "rec-ext",
    }
    last = result["billings"][-1]
    assert last["external_id"] == "send-2"
    assert last["substitute_id"] == "sub-2"
    assert last["recipient"]["external_id"] == "rec-2"
    assert captured[0]["params"]["start_invoice_date"] == "2026-08-01"
    assert captured[0]["params"]["end_invoice_date"] == "2026-08-31"
    assert captured[0]["params"]["start_index"] == 1
    assert captured[0]["params"]["count"] == 100
    assert captured[1]["params"]["start_index"] == 101
    assert len(captured) == 2


def test_retrieve_billings_sandbox_is_empty():
    provider = _provider()
    provider.is_mode_sandbox = lambda: True
    result = MailevaProvider.retrieve_billings(
        provider, "2026-08-01", "2026-08-31"
    )
    assert result == {"billings": []}
