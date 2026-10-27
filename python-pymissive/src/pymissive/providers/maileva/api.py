import logging
import time
from typing import Any, cast

import requests

from pymissive.utils import HTTP_TIMEOUT, _truthy
from .helpers import (
    _ADDRESS_OFFSET,
    _address_from_maileva_lines,
    _compact_http_error_detail,
    _maileva_address_line_6,
    _postal_api,
    _provider_custom_id,
    _require_maileva_line_1_or_2,
    _TOKEN_REFRESH_SKEW,
)
from .types import MailevaMixinTypingBase

logger = logging.getLogger(__name__)


class MailevaApiMixin(MailevaMixinTypingBase):
    @property
    def address_offset_letter(self) -> dict[str, str]:
        return _ADDRESS_OFFSET

    @property
    def address_offset_registered_letter(self) -> dict[str, str]:
        return _ADDRESS_OFFSET

    def get_postal_mode(self, product: str) -> str:
        return _postal_api(product)[0]

    def get_version(self, product: str) -> str:
        return _postal_api(product)[1]

    def is_mode_sandbox(self) -> bool:
        return _truthy(self._get_config_or_env("SANDBOX", False))

    def get_endpoint(self, endpoint: str, prefix: str = "api", *, product: str | None = None) -> str:
        template = self.endpoints[endpoint]
        needs_product = "{postal_mode}" in template or "{version}" in template
        if needs_product:
            postal_mode, version = _postal_api(product) if product else (None, None)
            if postal_mode is None:
                raise ValueError(f"Maileva endpoint {endpoint!r} requires a postal product")
        else:
            postal_mode, version = "", ""
        return template.format(
            base_url=self.get_base_url(prefix),
            postal_mode=postal_mode,
            version=version,
        )

    def get_base_url(self, prefix: str = "api") -> str:
        if prefix == "connexion":
            key = "BASE_TOKEN_URL_SANDBOX" if self.is_mode_sandbox() else "BASE_TOKEN_URL"
        else:
            key = "BASE_URL_SANDBOX" if self.is_mode_sandbox() else "BASE_URL"
        return str(self._get_config_or_env(key)).rstrip("/")

    def _invalidate_access_token(self) -> None:
        self._access_token = None
        self._access_token_expires_at = 0.0

    def _fetch_access_token(self) -> str:
        url = self.get_endpoint("auth", prefix="connexion")
        data = {
            "grant_type": "password",
            "username": self._get_config_or_env("USERNAME"),
            "password": self._get_config_or_env("PASSWORD"),
            "client_id": self._get_config_or_env("CLIENTID"),
            "client_secret": self._get_config_or_env("SECRET"),
        }
        response = requests.post(
            url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload["access_token"]
        expires_in = int(payload.get("expires_in") or 300)
        self._access_token = token
        self._access_token_expires_at = time.monotonic() + max(expires_in - _TOKEN_REFRESH_SKEW, 1)
        return token

    @property
    def access_token(self) -> str:
        token = getattr(self, "_access_token", None)
        expires_at = getattr(self, "_access_token_expires_at", 0.0)
        if token and time.monotonic() < expires_at:
            return token
        return self._fetch_access_token()

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Authenticated call; refresh the token and retry once on 401."""
        timeout = kwargs.pop("timeout", HTTP_TIMEOUT)
        extra_headers = dict(kwargs.pop("headers", None) or {})

        def _headers() -> dict[str, str]:
            headers = dict(extra_headers)
            if "Authorization" not in headers:
                headers.update(self._get_headers())
            if "files" in kwargs:
                headers.pop("Content-Type", None)
            return headers

        response = requests.request(method, url, headers=_headers(), timeout=timeout, **kwargs)
        if response.status_code != 401:
            return response
        self._invalidate_access_token()
        return requests.request(method, url, headers=_headers(), timeout=timeout, **kwargs)

    def _raise_for_response(self, response: requests.Response, context: str) -> None:
        """Raise on HTTP errors with a compact Maileva reason.

        The full body is on ``exc.response`` (and at DEBUG); it is not copied
        into the exception message, which is what Sentry and error mail show.
        """
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = (response.text or "").strip()
            summary = _compact_http_error_detail(body)
            if body:
                logger.debug(
                    "%s: Maileva HTTP %s body (%s bytes): %s",
                    context,
                    response.status_code,
                    len(body),
                    body,
                )
            detail = f" — {summary}" if summary else ""
            raise requests.HTTPError(
                f"{context}: {response.status_code} {response.reason}{detail}",
                response=response,
            ) from exc

    def _normalize_archiving_duration(self, value: Any) -> int:
        """Maileva accepts 3, 6 or 10 years; 0 is rejected by the API."""
        duration = int(value if value is not None else self._get_config_or_env("ARCHIVING_DURATION", 3))
        return duration if duration in (3, 6, 10) else 3

    def get_resource_types(self, resource_type: str) -> list[str]:
        from pymissive.config import normalize_missive_type

        key = normalize_missive_type(resource_type) or resource_type
        return [rt for rt, tp in self.resource_types.items() if tp == key]

    def get_normalize_type(self, data: dict[str, Any]) -> str:
        rt = data.get("resource_type")
        if not isinstance(rt, str):
            return "unknown"
        return self.resource_types.get(rt, "unknown")

    #########################################################
    # Webhooks (generic)
    #########################################################

    def _webhook_authentication(self) -> dict | None:
        secret = self.get_webhook_secret()
        if not secret:
            return None
        from pymissive.webhook_auth import (
            get_webhook_basic_login,
            maileva_subscription_authentication,
        )

        return maileva_subscription_authentication(secret, login=get_webhook_basic_login(self))

    def get_webhooks_by_resource_type_and_url(self, resource_type: str, url: str) -> list[dict[str, Any]]:
        webhooks = self.retrieve_webhooks()
        resource_types = self.get_resource_types(resource_type)
        return [
            webhook
            for webhook in webhooks
            if webhook.get("resource_type") in resource_types and webhook.get("callback_url") == url
        ]

    def _create_webhook_api(self, webhook_url: str, events: list[str], resource_type: list[str]) -> str | None:
        url = self.get_endpoint("subscriptions")
        first_response = None
        for rt in resource_type:
            for event in events:
                data: dict[str, Any] = {
                    "callback_url": webhook_url,
                    "event_type": event,
                    "resource_type": rt,
                }
                auth = self._webhook_authentication()
                if auth:
                    data["authentication"] = auth
                response = self._request("POST", url, json=data)
                response.raise_for_status()
                first_response = response.json() if first_response is None else first_response
        if first_response is None:
            return None
        return self.get_normalize_webhook_id({"id": first_response.get("id")})

    def retrieve_webhooks(self) -> list[dict[str, Any]]:
        url = self.get_endpoint("subscriptions")
        response = self._request("GET", url)
        response.raise_for_status()
        return response.json().get("subscriptions", [])

    def update_webhooks(self, resource_type: str, url: str, new_callback_url: str | None = None) -> bool:
        callback_url = new_callback_url or url
        webhooks = self.get_webhooks_by_resource_type_and_url(resource_type, url)
        for webhook in webhooks:
            endpoint = self.get_endpoint("subscriptions") + "/" + cast(str, webhook.get("id"))
            data: dict[str, Any] = {"callback_url": callback_url}
            auth = self._webhook_authentication()
            if auth:
                data["authentication"] = auth
            response = self._request("PATCH", endpoint, json=data)
            response.raise_for_status()
        return True

    def delete_webhooks(self, resource_type: str, url: str) -> bool:
        webhooks = self.get_webhooks_by_resource_type_and_url(resource_type, url)
        for webhook in webhooks:
            endpoint = self.get_endpoint("subscriptions") + "/" + cast(str, webhook.get("id"))
            response = self._request("DELETE", endpoint)
            response.raise_for_status()
        return True

    #########################################################
    # registered letter / letter - Recipients
    #########################################################

    def get_recipient_registered_letter_data(self, recipient: dict[str, Any]) -> dict[str, Any]:
        address = recipient.get("address")
        if not address:
            raise ValueError("Postal recipient requires address")
        data = {
            "address_line_1": address.get("organization"),
            "address_line_2": recipient.get("name"),
            "address_line_3": address.get("address_line2"),
            "address_line_4": address.get("address_line1"),
            "address_line_5": (address.get("locality") or address.get("po_box") or address.get("address_line3")),
            "address_line_6": _maileva_address_line_6(address, role="recipient address"),
            "country_code": (address.get("country_code") or "").upper() or None,
        }
        _require_maileva_line_1_or_2(
            data["address_line_1"],
            data["address_line_2"],
            role="recipient address",
        )
        custom_id = _provider_custom_id(recipient)
        if custom_id:
            data["custom_id"] = custom_id
        return data

    def _recipient_tracking_number(self, payload: dict[str, Any]) -> str | None:
        """Public carrier reference (La Poste, etc.), not Maileva's recipient id."""
        for key in ("tracking_number", "registered_number", "tracking_id"):
            value = payload.get(key)
            if value:
                return str(value)
        return None

    def _serialize_recipient_ref(self, recipient: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        local_id = recipient.get("id")
        custom_id = recipient.get("substitute_id") or payload.get("custom_id") or local_id
        data = {
            "internal_id": local_id or payload.get("custom_id"),
            "external_id": payload.get("id"),
        }
        if custom_id:
            data["substitute_id"] = str(custom_id)
        name = recipient.get("name") or payload.get("address_line_2")
        if name:
            data["name"] = name
        address = _address_from_maileva_lines(payload) or recipient.get("address")
        if address:
            data["address"] = address
        tracking_number = self._recipient_tracking_number(payload)
        if tracking_number:
            data["tracking_number"] = tracking_number
        return data

    def _detail_recipients_postal(self, external_id: str, *, product: str) -> list[dict[str, Any]]:
        url = self.get_endpoint("recipients", product=product) % external_id
        response = self._request("GET", url)
        response.raise_for_status()
        response = response.json()
        return response.get("recipients", [])

    def get_recipient_letter_data(self, recipient: dict[str, Any]) -> dict[str, Any]:
        return self.get_recipient_registered_letter_data(recipient)

    def _add_recipient(self, recipient: dict[str, Any], external_id: str, *, product: str) -> dict[str, Any]:
        url = self.get_endpoint("recipients", product=product) % external_id
        data = self.get_recipient_registered_letter_data(recipient)
        response = self._request("POST", url, json=data)
        self._raise_for_response(response, f"Maileva add recipient failed ({url})")
        return self._serialize_recipient_ref(recipient, response.json())

    def add_recipient_letter(self, recipient: dict[str, Any], external_id: str) -> dict[str, Any]:
        return self._add_recipient(recipient, external_id, product="letter")

    def add_recipient_registered_letter(self, recipient: dict[str, Any], external_id: str) -> dict[str, Any]:
        return self._add_recipient(recipient, external_id, product="registered_letter")

    def _update_recipient(self, recipient: dict[str, Any], external_id: str, *, product: str) -> dict[str, Any]:
        recipient_id = cast(str, recipient.get("external_id"))
        url = self.get_endpoint("recipients", product=product) % external_id + "/" + recipient_id
        data = self.get_recipient_registered_letter_data(recipient)
        response = self._request("PATCH", url, json=data)
        self._raise_for_response(response, f"Maileva update recipient failed ({url})")
        return self._serialize_recipient_ref(recipient, response.json())

    def update_recipient_letter(self, recipient: dict[str, Any], external_id: str) -> dict[str, Any]:
        return self._update_recipient(recipient, external_id, product="letter")

    def update_recipient_registered_letter(self, recipient: dict[str, Any], external_id: str) -> dict[str, Any]:
        return self._update_recipient(recipient, external_id, product="registered_letter")

    def _add_recipients_postal(
        self, recipients: list[dict[str, Any]], external_id: str, *, product: str
    ) -> list[dict[str, Any]]:
        external_ids = []
        for recipient in recipients:
            if recipient.get("external_id"):
                response = self._update_recipient(recipient, external_id, product=product)
            else:
                response = self._add_recipient(recipient, external_id, product=product)
            external_ids.append(response)
        return external_ids

    def _delete_recipient(self, recipient, external_id: str, *, product: str) -> Any:
        url = self.get_endpoint("recipients", product=product) % external_id + "/" + recipient.get("external_id")
        response = self._request("DELETE", url)
        response.raise_for_status()
        return response.json()

    def delete_recipient_letter(self, recipient, external_id: str) -> Any:
        return self._delete_recipient(recipient, external_id, product="letter")

    def delete_recipient_registered_letter(self, recipient, external_id: str) -> Any:
        return self._delete_recipient(recipient, external_id, product="registered_letter")

    def _delete_recipients(self, external_id: str, *, product: str) -> Any:
        url = self.get_endpoint("recipients", product=product) % external_id
        response = self._request("DELETE", url)
        response.raise_for_status()
        return response.json()

    def delete_recipients_letter(self, external_id: str) -> Any:
        return self._delete_recipients(external_id, product="letter")

    def delete_recipients_registered_letter(self, external_id: str) -> Any:
        return self._delete_recipients(external_id, product="registered_letter")
