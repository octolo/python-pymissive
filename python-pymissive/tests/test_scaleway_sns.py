"""Scaleway SNS confirmation host check and credential logging."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from pymissive.providers.scaleway import (
    ScalewayProvider,
    is_scaleway_sns_subscribe_url,
)
from pymissive.utils import HTTP_TIMEOUT


def _provider(**values):
    defaults = getattr(ScalewayProvider, "config_defaults", {}) or {}

    class _Configured(ScalewayProvider):
        def _get_config_or_env(self, key, default=None):
            if key in values:
                return values[key]
            if key in defaults:
                return defaults[key]
            return default

    return _Configured()


_OK = (
    "https://sns.mnq.fr-par.scaleway.com/"
    "?Action=ConfirmSubscription&TopicArn=arn:scw:sns:fr-par:x:t&Token=abc"
)


@pytest.mark.parametrize(
    "url",
    [
        _OK,
        "https://sns.mnq.nl-ams.scaleway.com/?Action=ConfirmSubscription&Token=1",
    ],
)
def test_subscribe_url_allows_scaleway_sns_confirm(url):
    assert is_scaleway_sns_subscribe_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "http://sns.mnq.fr-par.scaleway.com/?Action=ConfirmSubscription",
        "https://evil.example/?Action=ConfirmSubscription",
        "https://sns.mnq.fr-par.scaleway.com.evil.test/?Action=ConfirmSubscription",
        "https://sns.mnq.fr-par.scaleway.com/?Action=ListTopics",
        "https://user:pass@sns.mnq.fr-par.scaleway.com/?Action=ConfirmSubscription",
        "https://169.254.169.254/?Action=ConfirmSubscription",
        "https://api.scaleway.com/?Action=ConfirmSubscription",
    ],
)
def test_subscribe_url_rejects_non_scaleway_confirm(url):
    assert is_scaleway_sns_subscribe_url(url) is False


def test_confirm_gets_an_allowed_subscribe_url():
    provider = _provider()
    with patch("pymissive.providers.scaleway.requests.get") as get:
        provider._handle_webhook_email_confirm({"SubscribeURL": _OK})
    get.assert_called_once_with(_OK, timeout=HTTP_TIMEOUT, allow_redirects=False)


def test_confirm_does_not_fetch_a_forged_subscribe_url():
    provider = _provider()
    with patch("pymissive.providers.scaleway.requests.get") as get:
        with pytest.raises(ValueError, match="SubscribeURL"):
            provider._handle_webhook_email_confirm(
                {"SubscribeURL": "https://evil.test/?Action=ConfirmSubscription"}
            )
    get.assert_not_called()


def test_log_sns_credentials_prints_by_default(capsys):
    _provider(PROJECT_ID="p1").log_sns_credentials("ak", "sk")
    out = capsys.readouterr().out
    assert "SNS_ACCESS_KEY = ak" in out
    assert "SNS_SECRET_KEY = sk" in out


def test_log_sns_credentials_logger_uses_percent_formatting(caplog):
    provider = _provider(SCALEWAY_SNS_SAVE_METHOD="logger")
    with caplog.at_level(logging.INFO, logger="pymissive.providers.scaleway"):
        provider.log_sns_credentials("ak", "sk")
    assert "SNS_ACCESS_KEY = ak" in caplog.text
    assert "SNS_SECRET_KEY = sk" in caplog.text


def test_log_sns_credentials_file_is_opt_in_and_private(tmp_path):
    path = tmp_path / "sns.keys"
    _provider(SCALEWAY_SNS_CREDENTIALS_PATH=str(path)).log_sns_credentials("ak", "sk")
    assert path.read_text() == "SNS_ACCESS_KEY = ak\nSNS_SECRET_KEY = sk\n"
    assert (path.stat().st_mode & 0o777) == 0o600
