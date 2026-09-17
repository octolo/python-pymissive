"""SANDBOX env values are strings; only 1/true/yes/on must select sandbox URLs."""

import pytest

from pymissive.providers.maileva import MailevaProvider


class _Provider(MailevaProvider):
    def __init__(self, sandbox):
        self._sandbox = sandbox

    def _get_config_or_env(self, key, default=None):
        if key == "SANDBOX":
            return self._sandbox
        return MailevaProvider.config_defaults.get(key, default)


def test_sandbox_zero_string_uses_production_url():
    provider = _Provider("0")
    assert provider.is_mode_sandbox() is False
    assert provider.get_base_url() == "https://api.maileva.com"
    assert provider.get_base_url("connexion") == "https://connexion.maileva.com"


def test_sandbox_false_string_uses_production_url():
    provider = _Provider("False")
    assert provider.is_mode_sandbox() is False
    assert provider.get_base_url() == "https://api.maileva.com"


def test_sandbox_one_string_uses_sandbox_url():
    provider = _Provider("1")
    assert provider.is_mode_sandbox() is True
    assert provider.get_base_url() == "https://api.sandbox.maileva.net"
    assert provider.get_base_url("connexion") == "https://connexion.sandbox.maileva.net"


def test_sandbox_bool_true_uses_sandbox_url():
    assert _Provider(True).is_mode_sandbox() is True


def test_sandbox_bool_false_uses_production_url():
    assert _Provider(False).is_mode_sandbox() is False


class _PostalProvider(MailevaProvider):
    def __init__(self):
        pass

    def _get_config_or_env(self, key, default=None):
        return MailevaProvider.config_defaults.get(key, default)


def test_registered_letter_service_uses_registered_mail_v4():
    provider = _PostalProvider()
    assert provider.get_postal_mode("registered_letter") == "registered_mail"
    assert provider.get_version("registered_letter") == "v4"


def test_letter_service_uses_mail_v3():
    provider = _PostalProvider()
    assert provider.get_postal_mode("letter") == "mail"
    assert provider.get_version("letter") == "v3"


def test_address_offset_is_the_same_for_both_products():
    provider = _PostalProvider()
    assert provider.address_offset_letter == provider.address_offset_registered_letter
    assert provider.address_offset_registered_letter == {"top": "20mm", "width": "70mm", "height": "30mm"}


def test_reused_instance_does_not_stick_product_on_self():
    """ProviderKit may keep one Maileva instance; product is an argument, not state."""
    provider = _PostalProvider()
    letter_url = provider.get_endpoint("sendings", product="letter")
    registered_url = provider.get_endpoint("sendings", product="registered_letter")
    assert "/mail/v3/sendings" in letter_url
    assert "/registered_mail/v4/sendings" in registered_url
    assert not hasattr(provider, "_postal_product")

    data = provider.get_registered_letter_data(subject="Registered")
    assert data.get("acknowledgement_of_receipt") is True
    assert "postage_type" not in data

    data = provider.get_letter_data(subject="Simple")
    assert "acknowledgement_of_receipt" not in data
    assert "notification_types" not in data
    assert data.get("postage_type") == "FAST"


def test_postal_endpoint_requires_an_explicit_product():
    provider = _PostalProvider()
    with pytest.raises(ValueError, match="requires a postal product"):
        provider.get_endpoint("sendings")


def test_add_recipient_registered_letter_ignores_a_prior_letter_call():
    """Public *_registered_letter methods must not inherit a leftover letter URL."""
    captured = {}

    class _Capture(_PostalProvider):
        def _request(self, method, url, **kwargs):
            captured["url"] = url

            class _Resp:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"id": "r1"}

            return _Resp()

        def _raise_for_response(self, response, context):
            return None

    provider = _Capture()
    provider.get_endpoint("sendings", product="letter")
    provider.add_recipient_registered_letter(
        {
            "name": "A",
            "address": {
                "address_line1": "1 rue",
                "postal_code": "75001",
                "city": "Paris",
                "country_code": "FR",
            },
        },
        "sending-1",
    )
    assert "/registered_mail/v4/sendings/sending-1/recipients" in captured["url"]


def test_letter_has_delete_recipient_services():
    assert hasattr(MailevaProvider, "delete_recipient_letter")
    assert hasattr(MailevaProvider, "delete_recipients_letter")
    assert MailevaProvider.delete_recipient_letter is not MailevaProvider.delete_recipient_registered_letter


def test_letter_payload_ignores_acknowledgement():
    provider = _PostalProvider()
    data = provider.get_letter_data(
        subject="Letter", acknowledgement="acknowledgement_of_receipt"
    )
    assert "acknowledgement_of_receipt" not in data
    assert "notification_types" not in data
    assert data.get("postage_type") == "FAST"


def test_letter_webhook_resource_types_include_mail_v3():
    provider = _PostalProvider()
    types = provider.get_resource_types("letter")
    assert "mail/v3/sendings" in types
    assert "mail/v3/recipients" in types
    assert "mail/v2/sendings" in types


def test_registered_letter_basic_delivery_disables_ar():
    provider = _PostalProvider()
    data = provider.get_registered_letter_data(
        subject="registered letter", acknowledgement="basic_delivery"
    )
    assert data.get("acknowledgement_of_receipt") is False
    assert "acknowledgement_of_receipt_scanning" not in data
    assert "postage_type" not in data
    assert "notification_types" not in data


def test_registered_letter_acknowledgement_enables_ar():
    provider = _PostalProvider()
    data = provider.get_registered_letter_data(
        subject="registered letter",
        acknowledgement="acknowledgement_of_receipt",
        returned_mail_scanning=True,
    )
    assert data.get("acknowledgement_of_receipt") is True
    assert data.get("acknowledgement_of_receipt_scanning") is True


def test_registered_letter_explicit_ar_flag_wins():
    provider = _PostalProvider()
    data = provider.get_registered_letter_data(
        subject="registered letter",
        acknowledgement="acknowledgement_of_receipt",
        acknowledgement_of_receipt=False,
    )
    assert data.get("acknowledgement_of_receipt") is False


def test_letter_payload_sends_printing_flags_as_bools():
    provider = _PostalProvider()
    data = provider.get_letter_data(
        subject="Letter",
        color_printing=False,
        duplex_printing=True,
    )
    assert data["color_printing"] is False
    assert data["duplex_printing"] is True


def test_registered_letter_payload_sends_printing_flags_as_bools():
    provider = _PostalProvider()
    data = provider.get_registered_letter_data(
        subject="registered letter",
        color_printing=True,
        duplex_printing=False,
    )
    assert data["color_printing"] is True
    assert data["duplex_printing"] is False


def test_registered_letter_keeps_notification_types_when_email_is_set():
    provider = _PostalProvider()
    data = provider.get_registered_letter_data(
        subject="registered letter", notification_email="ops@example.com"
    )
    assert data["notification_email"] == "ops@example.com"
    assert data["notification_types"] == ["ALL_MAILEVA", "ALL_LAPOSTE"]


def test_letter_payload_uses_first_notification_recipient_email():
    provider = _PostalProvider()
    data = provider.get_letter_data(
        subject="Letter",
        notification=[
            {"name": "Ops", "email": "ops@example.com"},
            {"name": "Backup", "email": "backup@example.com"},
        ],
    )
    assert data["notification_email"] == "ops@example.com"
    assert "notification_types" not in data


def test_registered_letter_explicit_notification_email_wins_over_recipients():
    provider = _PostalProvider()
    data = provider.get_registered_letter_data(
        subject="registered letter",
        notification_email="override@example.com",
        notification=[{"email": "ops@example.com"}],
    )
    assert data["notification_email"] == "override@example.com"
    assert data["notification_types"] == ["ALL_MAILEVA", "ALL_LAPOSTE"]


def test_letter_payload_omits_notification_types_even_with_email():
    provider = _PostalProvider()
    data = provider.get_letter_data(subject="Letter", notification_email="ops@example.com")
    assert data["notification_email"] == "ops@example.com"
    assert "notification_types" not in data


def test_letter_and_registered_letter_are_distinct_services():
    from pymissive.config import provider_service_name

    assert provider_service_name("send", "letter") == "send_letter"
    assert provider_service_name("preview", "letter") == "preview_letter"
    assert provider_service_name("send", "registered_letter") == "send_registered_letter"
    assert hasattr(MailevaProvider, "send_letter")
    assert hasattr(MailevaProvider, "send_registered_letter")
    assert MailevaProvider.send_letter is not MailevaProvider.send_registered_letter


def test_letter_proofs_omit_acknowledgement_of_receipt():
    class _P(_PostalProvider):
        def _detail_recipients_postal(self, external_id, *, product):
            return [
                {
                    "address_line_2": "A",
                    "deposit_proof_url": "/d",
                    "acknowledgement_of_receipt_url": "/ar",
                }
            ]

    letter_urls = [doc["url"] for doc in _P().retrieve_proofs_letter(external_id="s")]
    registered_urls = [
        doc["url"] for doc in _P().retrieve_proofs_registered_letter(external_id="s")
    ]
    assert letter_urls == ["/d"]
    assert registered_urls == ["/d", "/ar"]


def test_letter_proofs_include_archive_url():
    class _P(_PostalProvider):
        def _detail_recipients_postal(self, external_id, *, product):
            return [{"address_line_2": "A", "archive_url": "/archive"}]

    assert [doc["url"] for doc in _P().retrieve_proofs_letter(external_id="s")] == ["/archive"]


def test_letter_tracking_skips_registered_deposit_proof():
    class _P(_PostalProvider):
        def _detail_recipients_postal(self, external_id, *, product):
            return [{"custom_id": "c", "id": "r", "deposit_proof_url": "/d"}]

        def _download_proof_bytes(self, url, *, product):
            raise AssertionError("letter must not download an LR deposit proof")

    result = _P().tracking_number_letter(external_id="s")
    assert "tracking_number" not in result[0]


def test_letter_tracking_uses_api_tracking_number():
    class _P(_PostalProvider):
        def _detail_recipients_postal(self, external_id, *, product):
            return [{"custom_id": "c", "id": "r", "tracking_number": "1E3232323"}]

        def _download_proof_bytes(self, url, *, product):
            raise AssertionError("letter tracking comes from the recipient API")

    result = _P().tracking_number_letter(external_id="s")
    assert result[0]["tracking_number"] == "1E3232323"
