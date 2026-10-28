from __future__ import annotations

from datetime import date
from types import MethodType
from unittest.mock import Mock, PropertyMock, call, patch

import pytest
import requests

from pymissive.providers.maileva import MailevaProvider
from pymissive.utils import HTTP_DOCUMENT_TIMEOUT, HTTP_TIMEOUT


def _provider(**values):
    defaults = MailevaProvider.config_defaults

    def get_config_or_env(self, key, default=None):
        return values.get(key, defaults.get(key, default))

    provider = MailevaProvider()
    provider._get_config_or_env = MethodType(get_config_or_env, provider)
    return provider


def _response(payload=None, *, status=200, text="", reason="OK"):
    response = Mock(spec=requests.Response)
    response.status_code = status
    response.text = text
    response.reason = reason
    response.content = text.encode()
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


def _address(**overrides):
    return {
        "organization": "Octolo",
        "address_line1": "1 rue du Test",
        "address_line2": "Bâtiment A",
        "postal_code": "75001",
        "city": "Paris",
        "country_code": "fr",
        **overrides,
    }


def test_api_endpoints_select_environment_and_require_product():
    live = _provider()
    sandbox = _provider(SANDBOX="yes")

    assert live.get_endpoint("sendings", product="letter") == "https://api.maileva.com/mail/v3/sendings"
    assert sandbox.get_endpoint("sendings", product="registered_letter") == (
        "https://api.sandbox.maileva.net/registered_mail/v4/sendings"
    )
    assert sandbox.get_endpoint("auth", prefix="connexion").startswith("https://connexion.sandbox.maileva.net/")
    with pytest.raises(ValueError, match="requires a postal product"):
        live.get_endpoint("sendings")
    with pytest.raises(ValueError, match="Unknown Maileva postal product"):
        live.get_endpoint("sendings", product="parcel")


def test_access_token_is_cached_and_refreshed():
    provider = _provider(USERNAME="user", PASSWORD="pass", CLIENTID="client", SECRET="secret")
    token_response = _response({"access_token": "token-1", "expires_in": 120})

    with (
        patch("pymissive.providers.maileva.api.requests.post", return_value=token_response) as post,
        patch("pymissive.providers.maileva.api.time.monotonic", side_effect=[10, 20, 80, 80]),
    ):
        assert provider.access_token == "token-1"
        assert provider.access_token == "token-1"
        token_response.json.return_value = {"access_token": "token-2"}
        assert provider.access_token == "token-2"

    assert post.call_count == 2
    assert post.call_args.kwargs["timeout"] == HTTP_TIMEOUT
    assert post.call_args.kwargs["data"]["grant_type"] == "password"


def test_authenticated_request_retries_once_on_unauthorized_and_handles_upload_headers():
    provider = _provider()
    first = _response(status=401, reason="Unauthorized")
    second = _response({"id": "doc-1"})

    with (
        patch.object(type(provider), "access_token", new_callable=PropertyMock, side_effect=["old", "new"]),
        patch("pymissive.providers.maileva.api.requests.request", side_effect=[first, second]) as request,
    ):
        result = provider._request("POST", "https://example.test/documents", files={"document": b"pdf"})

    assert result is second
    assert request.call_count == 2
    assert request.call_args_list[0].kwargs["headers"] == {"Authorization": "Bearer old"}
    assert request.call_args_list[1].kwargs["headers"] == {"Authorization": "Bearer new"}
    assert request.call_args.kwargs["timeout"] == HTTP_TIMEOUT


def test_authenticated_request_preserves_explicit_authorization_without_retry():
    provider = _provider()
    response = _response()
    with patch("pymissive.providers.maileva.api.requests.request", return_value=response) as request:
        assert provider._request("GET", "https://example.test", headers={"Authorization": "Basic x"}) is response
    assert request.call_args.kwargs["headers"] == {"Authorization": "Basic x"}


def test_http_error_exposes_compact_reason_without_recipient_payload():
    provider = _provider()
    response = _response(
        status=422,
        reason="Unprocessable Entity",
        text='{"message":"invalid address","errors":[{"field":"postal_code","message":"required"}],'
        '"recipient":{"name":"Private"}}',
    )

    with pytest.raises(requests.HTTPError) as exc_info:
        provider._raise_for_response(response, "Maileva create sending failed")

    message = str(exc_info.value)
    assert "invalid address" in message
    assert "postal_code: required" in message
    assert "Private" not in message
    assert exc_info.value.response is response


@pytest.mark.parametrize(("value", "expected"), [(None, 6), ("10", 10), (0, 3), (99, 3)])
def test_archiving_duration_is_normalized(value, expected):
    assert _provider(ARCHIVING_DURATION=6)._normalize_archiving_duration(value) == expected


def test_recipient_payload_and_reference_round_trip():
    provider = _provider()
    recipient = {
        "id": 12,
        "substitute_id": "contact-12",
        "name": "Ada Lovelace",
        "address": _address(locality="Quartier"),
    }

    payload = provider.get_recipient_registered_letter_data(recipient)
    reference = provider._serialize_recipient_ref(
        recipient,
        {**payload, "id": "recipient-uuid", "tracking_number": "1A2B"},
    )

    assert payload["address_line_2"] == "Ada Lovelace"
    assert payload["address_line_5"] == "Quartier"
    assert payload["address_line_6"] == "75001 Paris"
    assert payload["country_code"] == "FR"
    assert payload["custom_id"] == "contact-12"
    assert reference == {
        "internal_id": 12,
        "external_id": "recipient-uuid",
        "substitute_id": "contact-12",
        "name": "Ada Lovelace",
        "address": {
            "organization": "Octolo",
            "address_line1": "1 rue du Test",
            "address_line2": "Bâtiment A",
            "address_line3": "Quartier",
            "locality": "Quartier",
            "postal_code": "75001",
            "city": "Paris",
            "country_code": "FR",
        },
        "tracking_number": "1A2B",
    }


@pytest.mark.parametrize(
    "recipient",
    [
        {"name": "Ada"},
        {"name": "", "address": _address(organization="")},
        {"name": "Ada", "address": _address(postal_code="")},
    ],
)
def test_recipient_payload_rejects_incomplete_postal_address(recipient):
    with pytest.raises(ValueError):
        _provider().get_recipient_letter_data(recipient)


def test_recipient_crud_uses_product_endpoints_and_serializes_results():
    provider = _provider()
    recipient = {"id": "local-1", "name": "Ada", "address": _address()}
    created = _response({"id": "remote-1", "custom_id": "local-1"})
    updated = _response({"id": "remote-1", "custom_id": "local-1", "tracking_id": "TRACK"})
    deleted = _response({"deleted": True})

    with patch.object(provider, "_request", side_effect=[created, updated, deleted]) as request:
        created_ref = provider.add_recipient_letter(recipient, "sending-1")
        updated_ref = provider.update_recipient_letter({**recipient, "external_id": "remote-1"}, "sending-1")
        delete_result = provider.delete_recipient_letter({"external_id": "remote-1"}, "sending-1")

    assert created_ref["external_id"] == "remote-1"
    assert updated_ref["tracking_number"] == "TRACK"
    assert delete_result == {"deleted": True}
    assert request.call_args_list[0].args[:2] == (
        "POST",
        "https://api.maileva.com/mail/v3/sendings/sending-1/recipients",
    )
    assert request.call_args_list[1].args[0] == "PATCH"
    assert request.call_args_list[2].args[0] == "DELETE"


def test_webhook_api_creates_every_event_resource_pair_with_authentication():
    provider = _provider()
    responses = [_response({"id": f"wh-{index}"}) for index in range(4)]
    with (
        patch.object(provider, "_webhook_authentication", return_value={"type": "BASIC"}),
        patch.object(provider, "_request", side_effect=responses) as request,
    ):
        webhook_id = provider._create_webhook_api(
            "https://app.test/hook",
            ["ON_ACCEPTED", "ON_REJECTED"],
            ["mail/v3/sendings", "mail/v3/recipients"],
        )

    assert webhook_id == "maileva-wh-0"
    assert request.call_count == 4
    assert request.call_args_list[0].kwargs["json"]["authentication"] == {"type": "BASIC"}
    assert provider._create_webhook_api("https://app.test/hook", [], ["mail/v3/sendings"]) is None


def test_sending_payload_contracts():
    provider = _provider(ARCHIVING_DURATION=6, NOTIFICATION_TYPES=["ALL_MAILEVA"])
    common = {
        "id": 42,
        "subject": "  Contract ",
        "sender": {"name": "Octolo", "address": _address()},
        "notification": [{"email": "alerts@example.test"}],
        "custom_data": {"batch": "nightly"},
        "color_printing": "yes",
    }

    letter = provider.get_letter_data(**common, priority="urgent")
    registered = provider.get_registered_letter_data(**common, acknowledgement="basic_delivery")

    assert letter["name"] == "Contract"
    assert letter["custom_id"] == "42"
    assert letter["color_printing"] is True
    assert letter["duplex_printing"] is True
    assert letter["archiving_duration"] == 6
    assert letter["sender_country_code"] == "FR"
    assert letter["notification_email"] == "alerts@example.test"
    assert letter["postage_type"] == "URGENT"
    assert registered["acknowledgement_of_receipt"] is False
    assert registered["notification_types"] == ["ALL_MAILEVA"]


def test_stage_postal_reuses_existing_sending_and_adds_recipients():
    provider = _provider()
    detail = _response({"id": "sending-1", "name": "Existing"})
    recipients = [{"id": "contact-1", "name": "Ada", "address": _address()}]

    with (
        patch.object(provider, "_request", return_value=detail) as request,
        patch.object(provider, "_add_recipients_postal", return_value=[{"external_id": "recipient-1"}]) as add,
        patch.object(provider, "_add_attachments_postal", return_value=[]),
    ):
        external_id, staged_recipients, attachments = provider._stage_postal_before_submit(
            product="letter",
            external_id="sending-1",
            recipients=recipients,
        )

    request.assert_called_once_with("GET", "https://api.maileva.com/mail/v3/sendings/sending-1")
    add.assert_called_once_with(recipients, "sending-1", product="letter")
    assert external_id == "sending-1"
    assert staged_recipients == [{"external_id": "recipient-1"}]
    assert attachments == []


def test_send_postal_stages_then_submits():
    provider = _provider()
    submitted = _response(status=202, text="queued")
    with (
        patch.object(
            provider,
            "_stage_postal_before_submit",
            return_value=("sending-1", [{"external_id": "recipient-1"}], [{"external_id": "document-1"}]),
        ),
        patch.object(provider, "_request", return_value=submitted) as request,
    ):
        result = provider.send_registered_letter()

    request.assert_called_once_with(
        "POST",
        "https://api.maileva.com/registered_mail/v4/sendings/sending-1/submit",
    )
    assert result["event"] == "request"
    assert result["code"] == 202
    assert result["attachments"] == [{"external_id": "document-1"}]


def test_send_disabled_still_stages_without_submitting(monkeypatch):
    monkeypatch.setenv("PYMISSIVE_DISABLE_SEND", "1")
    provider = _provider()
    with (
        patch.object(provider, "_stage_postal_before_submit", return_value=("draft-1", [], [])),
        patch.object(provider, "_request") as request,
    ):
        result = provider.send_letter()

    request.assert_not_called()
    assert result["disabled_send"] is True
    assert result["external_id"] == "draft-1"


def test_preview_stages_without_submit_and_uses_temporary_custom_data():
    provider = _provider()
    with patch.object(provider, "_stage_postal_before_submit", return_value=("draft-1", [], [])) as stage:
        result = provider.preview_registered_letter(subject="Proof")

    assert stage.call_args.kwargs["custom_data"] == "pymissive_temporary_preview"
    assert result["event"] == "draft"
    assert result["id"] == "draft-1"


def test_attachment_crud_uses_multipart_timeout():
    provider = _provider()
    created = _response({"id": "document-1"})
    listed = _response([{"id": "document-1"}])
    deleted = _response()
    attachment = {"id": "local-doc", "name": "letter.pdf", "content": b"%PDF"}

    with patch.object(provider, "_request", side_effect=[created, listed, deleted]) as request:
        result = provider.add_attachment_letter(external_id="sending-1", attachment=attachment, priority=2)
        assert provider.get_attachments_letter(external_id="sending-1") == [{"id": "document-1"}]
        assert provider.delete_attachment_letter(external_id="sending-1", document_id="document-1") is True

    upload = request.call_args_list[0]
    assert upload.args[0] == "POST"
    assert upload.kwargs["timeout"] == HTTP_DOCUMENT_TIMEOUT
    assert upload.kwargs["files"]["document"] == ("letter.pdf", b"%PDF", "application/pdf")
    assert result == {"internal_id": "local-doc", "external_id": "document-1"}


def test_retrieve_postal_combines_detail_recipients_events_and_sender():
    provider = _provider()
    detail = {
        "id": "sending-1",
        "name": "Monthly letter",
        "submission_date": "2026-10-20T10:00:00Z",
        "sender_address_line_2": "Octolo",
        "sender_address_line_4": "1 rue du Test",
        "sender_address_line_6": "75001 Paris",
        "sender_country_code": "fr",
    }
    recipients = [
        {
            "id": "remote-1",
            "custom_id": "contact-1",
            "address_line_2": "Ada",
            "address_line_6": "69001 Lyon",
            "statuses": [{"code": "ACCEPTED", "date": "2026-10-20T10:01:00Z"}],
        },
        {"id": "remote-2", "custom_id": "contact-2", "status": "PENDING", "address_line_2": "Grace"},
    ]
    with (
        patch.object(provider, "_detail_sending_postal", return_value=detail),
        patch.object(provider, "_detail_recipients_postal", return_value=recipients),
    ):
        result = provider.retrieve_registered_letter(external_id="sending-1")

    assert result["subject"] == "Monthly letter"
    assert result["sender_name"] == "Octolo"
    assert result["sender_address"]["postal_code"] == "75001"
    assert [event["event"] for event in result["events"]] == ["ACCEPTED", "PENDING"]
    assert result["events"][0]["recipient"]["substitute_id"] == "contact-1"
    assert result["recipients"][0]["external_id"] == "remote-1"


def test_retrieve_normalizers_keep_existing_shapes_and_unknowns():
    provider = _provider()

    assert provider.get_normalize_events({"events": []}) == []
    assert provider.get_normalize_events({}) is None
    assert provider.get_normalize_sender_name({"sender_address_line_2": " Ada "}) == "Ada"
    existing = {"city": "Paris"}
    assert provider.get_normalize_sender_address({"sender_address": existing}) is existing
    assert provider.get_normalize_recipients({"recipients": "invalid"}) is None
    assert provider.get_normalize_event({"event_type": "ON_STATUS_ACCEPTED"}) == "accepted"
    assert provider.get_normalize_event({"event": None}) == "unknown"


def test_billing_pagination_and_serialization_contract():
    provider = _provider()
    first_items = [
        {
            "sending_id": f"sending-{index}",
            "recipient_id": f"recipient-{index}",
            "recipient_custom_id": f"contact-{index}",
            "user_reference": f"local-{index}",
            "amount": "1.25",
            "label": "Postage",
        }
        for index in range(100)
    ]
    second_items = [{"sending_id": "sending-100", "amount": 2, "currency": "USD"}]
    responses = [
        _response({"items": first_items, "paging": {"total_results": 101}}),
        _response({"invoice": {"items": second_items}, "paging": {"total_results": 101}}),
    ]

    with patch.object(provider, "_request", side_effect=responses) as request:
        result = provider.retrieve_billings(date(2026, 10, 1), "2026-10-31T23:59:59Z")

    assert len(result["billings"]) == 101
    assert result["billings"][0]["billing_amount"] == 1.25
    assert result["billings"][0]["recipient"] == {
        "id": "contact-0",
        "substitute_id": "contact-0",
        "external_id": "recipient-0",
    }
    assert result["billings"][-1]["currency"] == "USD"
    assert request.call_args_list == [
        call(
            "GET",
            "https://api.maileva.com/billing/v1/recipient_items",
            params={
                "start_invoice_date": "2026-10-01",
                "end_invoice_date": "2026-10-31",
                "start_index": 1,
                "count": 100,
            },
        ),
        call(
            "GET",
            "https://api.maileva.com/billing/v1/recipient_items",
            params={
                "start_invoice_date": "2026-10-01",
                "end_invoice_date": "2026-10-31",
                "start_index": 101,
                "count": 100,
            },
        ),
    ]


def test_billings_short_circuit_in_sandbox_and_without_reference():
    sandbox = _provider(SANDBOX=True)
    live = _provider()
    with patch.object(sandbox, "_request") as sandbox_request, patch.object(live, "_request") as live_request:
        assert sandbox.retrieve_billings("2026-01-01", "2026-01-31") == {"billings": []}
        assert sandbox.get_billings_letter(id="local-1") == []
        assert live.get_billings_registered_letter() == []
    sandbox_request.assert_not_called()
    live_request.assert_not_called()


def test_billing_http_error_uses_compact_api_error():
    provider = _provider()
    response = _response(status=500, reason="Server Error", text='{"message":"billing unavailable"}')
    with patch.object(provider, "_request", return_value=response):
        with pytest.raises(requests.HTTPError, match="billing unavailable"):
            provider.get_billings_letter(id="local-1")


def test_proof_listing_download_and_tracking_fallbacks():
    provider = _provider()
    recipients = [
        {
            "id": "remote-1",
            "custom_id": "contact-1",
            "address_line_2": "Ada / Lovelace",
            "deposit_proof_url": "/proofs/one",
            "tracking_number": "API-TRACK",
        },
        {"id": "remote-2", "custom_id": "contact-2", "deposit_proof_url": "/proofs/two"},
    ]
    downloaded = _response(text="%PDF proof")
    downloaded.content = b"%PDF proof"

    with (
        patch.object(provider, "_detail_recipients_postal", return_value=recipients),
        patch.object(provider, "_request", return_value=downloaded) as request,
        patch(
            "pymissive.providers.maileva.retrieve.extract_tracking_number_from_deposit_proof",
            side_effect=["RW799210633FR", None],
        ),
    ):
        proofs = provider.retrieve_proofs_registered_letter(external_id="sending-1")
        tracking = provider.tracking_number_registered_letter(external_id="sending-1")
        content = provider.download_proof_registered_letter(url="/proofs/one")

    assert proofs[0] == {"filename": "Ada__Lovelace_deposit_proof.pdf", "url": "/proofs/one"}
    assert tracking[0]["tracking_number"] == "RW799210633FR"
    assert tracking[1]["external_id"] == "remote-2"
    assert content == b"%PDF proof"
    assert request.call_args.kwargs == {"stream": True, "timeout": HTTP_DOCUMENT_TIMEOUT}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"sending_id": 42, "resource_id": "recipient"}, "42"),
        ({"event_detail": {"sending_id": "sending-detail"}}, "sending-detail"),
        ({"resource_name": "recipients", "resource_id": "recipient"}, None),
        ({"resource_type": "mail/v3/sendings", "resource_id": "sending-1"}, "sending-1"),
    ],
)
def test_webhook_external_id_normalization(payload, expected):
    assert _provider().get_normalize_external_id(payload) == expected


def test_webhook_payload_and_recipient_normalization():
    provider = _provider()
    payload = bytearray(b'{"event_type":"ON_STATUS_ACCEPTED","resource_custom_id":"contact-1",')
    payload += b'"resource_type":"mail/v3/recipients"}'
    decoded = provider.handle_webhook_letter(payload)

    assert decoded["event_type"] == "ON_STATUS_ACCEPTED"
    assert provider.get_normalize_recipient(decoded) == {"id": "contact-1", "substitute_id": "contact-1"}
    assert provider.get_normalize_recipient({"recipient": {"id": "contact-2", "name": "Grace"}}) == {
        "id": "contact-2",
        "substitute_id": "contact-2",
        "name": "Grace",
    }
    assert provider.get_normalize_recipient({"resource_type": "mail/v3/sendings"}) is None


def test_webhook_mixin_filters_creates_updates_and_deletes():
    provider = _provider()
    webhooks = [
        {"id": "1", "resource_type": "mail/v3/sendings", "callback_url": "https://old.test/hook"},
        {"id": "2", "resource_type": "registered_mail/v4/recipients", "callback_url": "https://other.test/hook"},
        {"id": "3", "resource_type": "email", "callback_url": "https://ignored.test/hook"},
    ]
    with (
        patch.object(provider, "retrieve_webhooks", return_value=webhooks),
        patch.object(provider, "_create_webhook_api", return_value="maileva-new") as create,
        patch.object(provider, "update_webhooks", return_value=True) as update,
        patch.object(provider, "delete_webhooks", return_value=True) as delete,
    ):
        assert provider.create_webhook_letter({"url": "https://new.test/hook"}) == "maileva-new"
        assert len(provider._retrieve_webhooks_registered_letter()) == 2
        assert provider.update_webhook_letter({"webhook_id": "maileva-1", "url": "https://old.test/hook"})
        assert provider.delete_webhook_letter({"webhook_id": "maileva-1"})

    assert create.call_args.args[0] == "https://new.test/hook"
    assert all(event.startswith("ON_") for event in create.call_args.args[1])
    update.assert_called_once_with("letter", "https://old.test/hook", "https://old.test/hook")
    delete.assert_called_once_with("letter", "https://old.test/hook")


def test_webhook_mixin_rejects_unknown_id_without_url():
    provider = _provider()
    with patch.object(provider, "retrieve_webhooks", return_value=[]):
        with pytest.raises(ValueError, match="Cannot update webhook"):
            provider.update_webhook_registered_letter({"webhook_id": "maileva-missing"})
        with pytest.raises(ValueError, match="Cannot delete webhook"):
            provider.delete_webhook_registered_letter({})
