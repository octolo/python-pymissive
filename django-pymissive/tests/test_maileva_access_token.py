"""Maileva tokens expire; a 401 refreshes once instead of looping."""

from __future__ import annotations

from unittest.mock import Mock, patch

from pymissive.providers.maileva import MailevaProvider


class _Provider(MailevaProvider):
    def __init__(self):
        pass

    def _get_config_or_env(self, key, default=None):
        values = {
            "USERNAME": "user",
            "PASSWORD": "pass",
            "CLIENTID": "client",
            "SECRET": "secret",
            "SANDBOX": False,
        }
        return values.get(key, default if default is not None else MailevaProvider.config_defaults.get(key))


def _token_response(token: str, expires_in: int = 300) -> Mock:
    response = Mock()
    response.status_code = 200
    response.raise_for_status = Mock()
    response.json.return_value = {"access_token": token, "expires_in": expires_in}
    return response


def test_access_token_is_reused_until_it_expires():
    provider = _Provider()
    with patch(
        "pymissive.providers.maileva.requests.post",
        return_value=_token_response("tok-1"),
    ) as post:
        assert provider.access_token == "tok-1"
        assert provider.access_token == "tok-1"
    assert post.call_count == 1


def test_access_token_is_fetched_again_after_expiry():
    provider = _Provider()
    with patch(
        "pymissive.providers.maileva.requests.post",
        side_effect=[_token_response("tok-1"), _token_response("tok-2")],
    ) as post:
        assert provider.access_token == "tok-1"
        provider._access_token_expires_at = 0
        assert provider.access_token == "tok-2"
    assert post.call_count == 2


def test_request_refreshes_token_and_retries_once_on_401():
    provider = _Provider()
    unauthorized = Mock(status_code=401)
    ok = Mock(status_code=200)
    with (
        patch(
            "pymissive.providers.maileva.requests.post",
            side_effect=[_token_response("old"), _token_response("new")],
        ),
        patch(
            "pymissive.providers.maileva.requests.request",
            side_effect=[unauthorized, ok],
        ) as request,
    ):
        response = provider._request("GET", "https://api.maileva.com/sendings/1")

    assert response is ok
    assert request.call_count == 2
    first_auth = request.call_args_list[0].kwargs["headers"]["Authorization"]
    second_auth = request.call_args_list[1].kwargs["headers"]["Authorization"]
    assert first_auth == "Bearer old"
    assert second_auth == "Bearer new"


def test_request_does_not_retry_a_second_401():
    provider = _Provider()
    first = Mock(status_code=401)
    second = Mock(status_code=401)
    with (
        patch(
            "pymissive.providers.maileva.requests.post",
            return_value=_token_response("tok"),
        ),
        patch(
            "pymissive.providers.maileva.requests.request",
            side_effect=[first, second],
        ) as request,
    ):
        response = provider._request("GET", "https://api.maileva.com/sendings/1")

    assert response is second
    assert request.call_count == 2
