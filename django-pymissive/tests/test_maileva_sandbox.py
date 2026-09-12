"""SANDBOX env values are strings; only 1/true/yes/on must select sandbox URLs."""

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


class _AckProvider(MailevaProvider):
    def __init__(self):
        self.ack_level = None


def test_acknowledgement_of_receipt_uses_registered_mail_v4():
    provider = _AckProvider()
    assert provider.is_acknowledgement_of_receipt(
        acknowledgement="acknowledgement_of_receipt"
    )
    assert provider.get_lre_mode() == "registered_mail"
    assert provider.get_version() == "v4"


def test_basic_delivery_uses_mail_v2():
    provider = _AckProvider()
    assert provider.is_acknowledgement_of_receipt(acknowledgement="basic_delivery") is False
    assert provider.get_lre_mode() == "mail"
    assert provider.get_version() == "v2"
