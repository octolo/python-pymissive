import json
import logging
import re
import time
import zlib
from datetime import datetime, timezone as dt_timezone
from typing import Any

import requests

from pymissive.utils import HTTP_DOCUMENT_TIMEOUT, HTTP_TIMEOUT, _truthy, is_disable_send
from .base import MissiveProviderBase

logger = logging.getLogger(__name__)

#: Refresh this many seconds before Keycloak's ``expires_in``.
_TOKEN_REFRESH_SKEW = 60

#: Keys Maileva (and similar APIs) use for the *reason*, not the echoed payload.
_HTTP_ERROR_REASON_KEYS = (
    "code",
    "error",
    "error_code",
    "error_description",
    "message",
    "detail",
    "title",
)


def _compact_http_error_detail(body: str, *, limit: int = 400) -> str:
    """Keep the validation reason; drop the sending/recipient echo.

    The full body stays on ``HTTPError.response`` for a debugger. Putting it
    in the exception message ships names and addresses to Sentry and Django
    error mail.
    """
    if not body:
        return ""
    try:
        payload = json.loads(body)
    except ValueError:
        return ""
    parts: list[str] = []
    if isinstance(payload, dict):
        for key in _HTTP_ERROR_REASON_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        errors = payload.get("errors")
        if isinstance(errors, list):
            for item in errors[:8]:
                if not isinstance(item, dict):
                    continue
                field = str(item.get("field") or item.get("path") or "").strip()
                msg = str(
                    item.get("message") or item.get("code") or item.get("error") or ""
                ).strip()
                bit = ": ".join(piece for piece in (field, msg) if piece)
                if bit:
                    parts.append(bit)
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        if part not in seen:
            seen.add(part)
            unique.append(part)
    summary = " — ".join(unique)
    if len(summary) > limit:
        return summary[: limit - 3] + "..."
    return summary


#: Envelope window. mail/v2 and registered_mail/v4 use the same placement.
_ADDRESS_OFFSET_LRE = {
    "top": "20mm",
    "width": "70mm",
    "height": "30mm",
}

# International registered mail (UPU S10), e.g. RW799210633FR.
_UPU_S10_RE = re.compile(r"\b[A-Z]{2}\d{9}[A-Z]{2}\b")
# Domestic La Poste LR number printed under "Numéro de la LR" (13 or 15 digits).
_FR_LR_RE = re.compile(r"(?<!\d)(\d{15}|\d{13})(?!\d)")


_MAILEVA_PO_BOX_RE = re.compile(
    r"^(?:BP|CS|TSA|B\.?\s*P\.?|BO[IÎ]TE\s*POSTALE)\b",
    re.IGNORECASE,
)


def _provider_custom_id(data: dict[str, Any] | None) -> str | None:
    """Maileva ``custom_id`` is the client substitute_id, else the local id."""
    if not data:
        return None
    value = data.get("substitute_id") or data.get("id")
    if value in (None, ""):
        return None
    return str(value)


def _is_maileva_country_prefix(token: str) -> bool:
    return bool(token) and token.isalpha() and 1 <= len(token) <= 3


def _geoaddress_from_maileva_line_5(line: str) -> dict[str, str]:
    """Line 5 is extra address info (``address_line3``), plus po_box or locality."""
    line = (line or "").strip()
    if not line:
        return {}
    extra = {"address_line3": line}
    if _MAILEVA_PO_BOX_RE.match(line):
        extra["po_box"] = line
    else:
        extra["locality"] = line
    return extra


def _require_maileva_line_1_or_2(line_1, line_2, *, role: str) -> None:
    """Maileva: société (line 1) or name (line 2), at least one.

    https://www.maileva.com/changelog/ — ADDRESS_LINE_1_OR_ADDRESS_LINE_2_MANDATORY
    """
    if str(line_1 or "").strip() or str(line_2 or "").strip():
        return
    raise ValueError(f"Maileva {role} requires address_line_1 or address_line_2")


def _maileva_address_line_6(address: dict[str, Any], *, role: str = "address") -> str:
    """Build Maileva ``address_line_6`` (``75000 Paris``).

    Both ``postal_code`` and ``city`` are required. An f-string of missing
    keys would print ``None None`` on the envelope.
    """
    postal_code = str(address.get("postal_code") or "").strip()
    city = str(address.get("city") or "").strip()
    if not postal_code or not city:
        raise ValueError(f"Maileva {role} requires postal_code and city")
    line = f"{postal_code} {city}"
    sorting_code = str(address.get("sorting_code") or "").strip()
    if sorting_code:
        line = f"{line} {sorting_code}"
    return line


def _parse_maileva_address_line_6(line: str) -> dict[str, str]:
    """Split Maileva ``address_line_6`` into geoaddress city / postal / state.

    Domestic: ``75000 Paris``. International: ``I 39044 EGNA BZ ITALIE``.
    ``country_code`` comes from the Maileva payload, not from this line.
    """
    tokens = (line or "").split()
    if not tokens:
        return {}
    result: dict[str, str] = {}
    international = False
    i = 0
    if len(tokens) >= 2 and _is_maileva_country_prefix(tokens[0]) and any(
        c.isdigit() for c in tokens[1]
    ):
        international = True
        i = 1
    if i < len(tokens) and any(c.isdigit() for c in tokens[i]):
        result["postal_code"] = tokens[i]
        i += 1
    rest = tokens[i:]
    if (
        len(rest) >= 2
        and _is_maileva_country_prefix(rest[0])
        and rest[1] == result.get("postal_code")
    ):
        international = True
        rest = rest[2:]
    if international and rest and rest[-1].isalpha() and len(rest[-1]) > 2:
        rest = rest[:-1]
    if rest and len(rest[-1]) == 2 and rest[-1].isalpha():
        result["state_code"] = rest[-1].upper()
        rest = rest[:-1]
    cedex_at = next(
        (idx for idx, token in enumerate(rest) if token.upper() == "CEDEX"),
        None,
    )
    if cedex_at is not None:
        result["sorting_code"] = " ".join(rest[cedex_at:])
        rest = rest[:cedex_at]
    if rest:
        result["city"] = " ".join(rest)
    return result


def _address_from_maileva_lines(
    payload: dict[str, Any],
    *,
    prefix: str = "",
    country_key: str = "country_code",
) -> dict[str, str] | None:
    """Reverse Maileva recipient/sender lines into a geoaddress dict.

    ``address_line_1`` organization, ``_2`` name (caller), ``_3`` address_line2,
    ``_4`` address_line1, ``_5`` po_box/locality, ``_6`` postal_code + city.
    ``country_code`` is a dedicated Maileva field.
    """

    def line(n: int) -> str:
        return (payload.get(f"{prefix}address_line_{n}") or "").strip()

    address = {
        "organization": line(1) or None,
        "address_line2": line(3) or None,
        "address_line1": line(4) or None,
        "country_code": (payload.get(country_key) or "").strip().upper() or None,
    }
    address.update(_geoaddress_from_maileva_line_5(line(5)))
    address.update(_parse_maileva_address_line_6(line(6)))
    return {key: value for key, value in address.items() if value} or None


def _inflate_pdf_stream(raw: bytes) -> bytes | None:
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            continue
    return None


def _iter_pdf_streams(pdf_bytes: bytes):
    for match in re.finditer(rb"stream\r?\n", pdf_bytes):
        start = match.end()
        end = pdf_bytes.find(b"endstream", start)
        if end < 0:
            continue
        raw = pdf_bytes[start:end].rstrip(b"\r\n")
        inflated = _inflate_pdf_stream(raw)
        yield inflated if inflated is not None else raw


def _pdf_tounicode_map(streams) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for stream in streams:
        if b"beginbfrange" not in stream and b"beginbfchar" not in stream:
            continue
        for lo, hi, dst in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
            stream,
        ):
            lo_i, hi_i, dst_i = int(lo, 16), int(hi, 16), int(dst, 16)
            for offset, code in enumerate(range(lo_i, hi_i + 1)):
                mapping[code] = chr(dst_i + offset)
        for block in re.findall(rb"beginbfchar(.*?)endbfchar", stream, flags=re.DOTALL):
            for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                mapping[int(src, 16)] = chr(int(dst, 16))
    return mapping


def _pdf_unescape_literal(raw: bytes) -> str:
    out = bytearray()
    i = 0
    while i < len(raw):
        if raw[i] != 0x5C or i + 1 >= len(raw):
            out.append(raw[i])
            i += 1
            continue
        nxt = raw[i + 1]
        simple = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
        if nxt in simple:
            out.append(simple[nxt])
            i += 2
        elif 0x30 <= nxt <= 0x37:
            j = i + 1
            octal = b""
            while j < len(raw) and len(octal) < 3 and 0x30 <= raw[j] <= 0x37:
                octal += bytes([raw[j]])
                j += 1
            out.append(int(octal, 8))
            i = j
        else:
            out.append(nxt)
            i += 2
    return out.decode("latin-1", "replace")


def _pdf_decode_hex_tj(hexstr: str, mapping: dict[int, str]) -> str:
    if len(hexstr) % 2:
        return ""
    width = 4 if mapping and max(mapping, default=0) > 255 else 2
    if len(hexstr) % width:
        width = 2 if width == 4 else 4
        if len(hexstr) % width:
            return ""
    chars = []
    for i in range(0, len(hexstr), width):
        code = int(hexstr[i:i + width], 16)
        chars.append(mapping.get(code, chr(code) if code < 256 else ""))
    return "".join(chars)


def _extract_deposit_proof_text(pdf_bytes: bytes) -> str:
    streams = list(_iter_pdf_streams(pdf_bytes))
    mapping = _pdf_tounicode_map(streams)
    parts: list[str] = []
    for stream in streams:
        for match in re.finditer(rb"\((?:\\.|[^\\)])*\)\s*Tj", stream):
            inner = match.group(0)
            inner = inner[1:inner.rfind(b")")]
            parts.append(_pdf_unescape_literal(inner))
        for match in re.finditer(rb"<([0-9A-Fa-f]+)>\s*Tj", stream):
            decoded = _pdf_decode_hex_tj(match.group(1).decode("ascii"), mapping)
            if decoded:
                parts.append(decoded)
    return "\n".join(parts)


def extract_tracking_number_from_deposit_proof(pdf_bytes: bytes) -> str | None:
    """Read the carrier tracking number printed on a Maileva deposit-proof PDF.

    International proofs expose UPU S10 under ``NUMERO DE RECOMMANDE``
    (e.g. ``RW799210633FR``). Domestic French LR proofs print a 13- or
    15-digit number under ``Numéro de la LR``.
    """
    text = _extract_deposit_proof_text(pdf_bytes)
    upu = _UPU_S10_RE.findall(text.upper())
    if upu:
        return upu[0]
    for number in _FR_LR_RE.findall(text):
        return number
    return None


class MailevaProvider(MissiveProviderBase):
    """Maileva LRE provider (electronic registered letter, registered mail)."""

    #########################################################
    # Metadata / Configuration
    #########################################################

    name = "maileva"
    display_name = "Maileva"
    description = "LRE (electronic registered letter) and registered mail services"
    required_packages = ["requests"]
    config_keys = [
        "CLIENTID", "SECRET", "USERNAME", "PASSWORD", "SANDBOX",
        "ARCHIVING_DURATION",
        "PRINT_SENDER_ADDRESS",
        "DUPLEX_PRINTING",
        "COLOR_PRINTING",
        "POSTAGE_TYPE",
    ]
    config_defaults = {
        "SANDBOX": False,
        "ARCHIVING_DURATION": 3,
        "PRINT_SENDER_ADDRESS": True,
        "DUPLEX_PRINTING": True,
        "COLOR_PRINTING": False,
        "POSTAGE_TYPE": "FAST",
        "BASE_URL_SANDBOX": "https://api.sandbox.maileva.net",
        "BASE_URL": "https://api.maileva.com",
        "BASE_TOKEN_URL_SANDBOX": "https://connexion.sandbox.maileva.net",
        "BASE_TOKEN_URL": "https://connexion.maileva.com",
    }
    endpoints = {
        'auth': '{base_url}/auth/realms/services/protocol/openid-connect/token',
        'sendings': '{base_url}/{postal_mode}/{version}/sendings',
        'documents': '{base_url}/{postal_mode}/{version}/sendings/%s/documents',
        'recipients': '{base_url}/{postal_mode}/{version}/sendings/%s/recipients',
        'submit': '{base_url}/{postal_mode}/{version}/sendings/%s/submit',
        'delete': '{base_url}/{postal_mode}/{version}/sendings/%s',
        'prooflist': '{base_url}/{postal_mode}/{version}/global_deposit_proofs?sending_id=%s',
        'proof': '{base_url}/{postal_mode}/{version}/global_deposit_proofs/%s',
        'proofdownload': '{base_url}/{postal_mode}/{version}%s',
        'invoice': '{base_url}/billing/v1/recipient_items',
        'subscriptions': '{base_url}/notification_center/v2/subscriptions',
    }
    events_association = {
        "ON_STATUS_ACCEPTED": "accepted",
        "ON_STATUS_REJECTED": "rejected",
        "ON_STATUS_PROCESSED": "processed",
        "ON_STATUS_PROCESSED_WITH_ERRORS": "error",
        "ON_DEPOSIT_PROOF_RECEIVED": "deposit_proof",
        "ON_GLOBAL_DEPOSIT_PROOF_RECEIVED": "deposit_proof",
        "ON_CONTENT_PROOF_RECEIVED": "proof_of_content",
        "ON_ACKNOWLEDGEMENT_OF_RECEIPT_RECEIVED": "proofs_of_delivery",
        "ON_STATUS_ARCHIVED": "archived",
        "ON_MAIN_DELIVERY_STATUS_FIRST_PRESENTATION": "attempted_delivery",
        "ON_MAIN_DELIVERY_STATUS_DELIVERED": "delivered",
        "ON_MAIN_DELIVERY_STATUS_UNDELIVERED": "undelivered",
        "ON_UNDELIVERED_MAIL_RECEIVED": "undelivered",
        "request": "request",
        "DRAFT": "request",
        "PENDING": "queued",
        "ACCEPTED": "accepted",
        "PREPARING": "processing",
        "PROCESSED": "processed",
        "PROCESSED_WITH_ERRORS": "error",
        "REJECTED": "rejected",
        "ARCHIVED": "archived",
    }
    fields_associations = {
        "webhook_id": "id",
        "internal_id": ("custom_id", "resource_custom_id"),
        "substitute_id": "custom_id",
        "external_id": ("sending_id", "resource_id"),
        "id": ("id", "resource_id"),
        "url": ["url", "callback_url"],
        "type": "resource_type",
        "occurred_at": ("event_date", "event_timestamp"),
    }
    resource_types = {
        "registered_mail/v4/sendings": "lre",
        "registered_mail/v4/recipients": "lre",
        "registered_mail/v2/sendings": "lre",
        "registered_mail/v2/recipients": "lre",
    }
    proof_keys = [
        "content_proof_embedded_document",
        "deposit_proof",
        "content_proof",
        "acknowledgement_of_receipt",
    ]
    ack_level = None

    #########################################################
    # Helpers
    #########################################################

    @property
    def address_offset_lre(self) -> dict[str, str]:
        return _ADDRESS_OFFSET_LRE

    def get_lre_mode(self) -> str:
        return "registered_mail" if self.is_acknowledgement_of_receipt() else "mail"

    def get_version(self) -> str:
        return "v4" if self.is_acknowledgement_of_receipt() else "v2"

    def is_mode_sandbox(self) -> bool:
        return _truthy(self._get_config_or_env("SANDBOX", False))

    def get_endpoint(self, endpoint: str, prefix: str = "api") -> str:
        return self.endpoints[endpoint].format(
            base_url=self.get_base_url(prefix),
            postal_mode=self.get_lre_mode(),
            version=self.get_version(),
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
        self._access_token_expires_at = time.monotonic() + max(
            expires_in - _TOKEN_REFRESH_SKEW, 1
        )
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
        headers = dict(kwargs.pop("headers", None) or {})
        if "Authorization" not in headers:
            headers.update(self._get_headers())
        if "files" in kwargs:
            headers.pop("Content-Type", None)
        response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        if response.status_code != 401:
            return response
        self._invalidate_access_token()
        headers.update(self._get_headers())
        if "files" in kwargs:
            headers.pop("Content-Type", None)
        return requests.request(method, url, headers=headers, timeout=timeout, **kwargs)

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
        return [rt for rt, tp in self.resource_types.items() if tp == resource_type]

    def get_normalize_type(self, data: dict[str, Any]) -> str:
        rt = data.get("resource_type")
        return self.resource_types.get(rt, "unknown")

    #########################################################
    # Webhooks (generic)
    #########################################################

    def get_webhooks_by_resource_type_and_url(self, resource_type: str, url: str) -> list[dict[str, Any]]:
        webhooks = self.retrieve_webhooks()
        resource_types = self.get_resource_types(resource_type)
        return [
            webhook for webhook in webhooks
            if webhook.get("resource_type") in resource_types and webhook.get("callback_url") == url
        ]

    def _create_webhook_api(self, webhook_url: str, events: list[str], resource_type: list[str]) -> str | None:
        url = self.get_endpoint('subscriptions')
        first_response = None
        for rt in resource_type:
            for event in events:
                data = {
                    "callback_url": webhook_url,
                    "event_type": event,
                    "resource_type": rt,
                }
                response = self._request("POST", url, json=data)
                response.raise_for_status()
                first_response = response.json() if first_response is None else first_response
        return self.get_normalize_webhook_id({"id": first_response.get("id")})

    def retrieve_webhooks(self) -> list[dict[str, Any]]:
        url = self.get_endpoint('subscriptions')
        response = self._request("GET", url)
        response.raise_for_status()
        return response.json().get("subscriptions", [])

    def update_webhooks(self, resource_type: str, url: str, new_callback_url: str | None = None) -> bool:
        callback_url = new_callback_url or url
        webhooks = self.get_webhooks_by_resource_type_and_url(resource_type, url)
        for webhook in webhooks:
            endpoint = self.get_endpoint('subscriptions') + "/" + webhook.get("id")
            data = {"callback_url": callback_url}
            response = self._request("PATCH", endpoint, json=data)
            response.raise_for_status()
        return True

    def delete_webhooks(self, resource_type: str, url: str) -> bool:
        webhooks = self.get_webhooks_by_resource_type_and_url(resource_type, url)
        for webhook in webhooks:
            endpoint = self.get_endpoint('subscriptions') + "/" + webhook.get("id")
            response = self._request("DELETE", endpoint)
            response.raise_for_status()
        return True

    #########################################################
    # LRE - Recipients
    #########################################################

    def get_recipient_lre_data(self, recipient: dict[str, Any]) -> dict[str, Any]:
        address = recipient.get("address")
        if not address:
            raise ValueError("LRE recipient requires address")
        data = {
            "address_line_1": address.get("organization"),
            "address_line_2": recipient.get("name"),
            "address_line_3": address.get("address_line2"),
            "address_line_4": address.get("address_line1"),
            "address_line_5": (
                address.get("locality")
                or address.get("po_box")
                or address.get("address_line3")
            ),
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

    def _serialize_recipient_ref(
        self, recipient: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        local_id = recipient.get("id")
        custom_id = (
            recipient.get("substitute_id")
            or payload.get("custom_id")
            or local_id
        )
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

    def _detail_recipients_lre(self, external_id: str) -> list[dict[str, Any]]:
        url = self.get_endpoint('recipients') % external_id
        response = self._request("GET", url)
        response.raise_for_status()
        response = response.json()
        return response.get("recipients", [])

    def add_recipient_lre(self, recipient: dict[str, Any], external_id: str) -> dict[str, Any]:
        url = self.get_endpoint('recipients') % external_id
        data = self.get_recipient_lre_data(recipient)
        response = self._request("POST", url, json=data)
        self._raise_for_response(response, f"Maileva add recipient failed ({url})")
        return self._serialize_recipient_ref(recipient, response.json())

    def update_recipient_lre(self, recipient: dict[str, Any], external_id: str) -> dict[str, Any]:
        url = self.get_endpoint('recipients') % external_id + "/" + recipient.get("external_id")
        data = self.get_recipient_lre_data(recipient)
        response = self._request("PATCH", url, json=data)
        self._raise_for_response(response, f"Maileva update recipient failed ({url})")
        return self._serialize_recipient_ref(recipient, response.json())

    def _add_recipients_lre(self, recipients: list[dict[str, Any]], external_id: str) -> list[dict[str, Any]]:
        external_ids = []
        for recipient in recipients:
            if recipient.get("external_id"):
                response = self.update_recipient_lre(recipient, external_id)
            else:
                response = self.add_recipient_lre(recipient, external_id)
            external_ids.append(response)
        return external_ids

    def delete_recipient_lre(self, recipient, external_id: str) -> Any:
        url = self.get_endpoint('recipients') % external_id + "/" + recipient.get("external_id")
        response = self._request("DELETE", url)
        response.raise_for_status()
        return response.json()

    def delete_recipients_lre(self, external_id: str) -> Any:
        url = self.get_endpoint('recipients') % external_id
        response = self._request("DELETE", url)
        response.raise_for_status()
        return response.json()

    #########################################################
    # LRE - Sendings (create, update, delete, send)
    # Maileva: no separate "cancel sending" API; removing a sending uses HTTP DELETE (delete_lre).
    #########################################################

    def is_acknowledgement_of_receipt(self, **kwargs: Any) -> bool:
        """Whether this call is registered-mail (v4), not the previous missive.

        ``get_endpoint`` / ``get_version`` read the value set by the last
        public method that passed ``**kwargs``. A reused provider instance
        (ProviderKit) must not keep the first missive's product.
        """
        if kwargs:
            self.ack_level = kwargs.get("acknowledgement")
        return self.ack_level == "acknowledgement_of_receipt"

    def get_lre_data(self, **kwargs: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": (kwargs.get("subject") or "").strip() or "Missive",
        }
        custom_id = _provider_custom_id(kwargs)
        if custom_id:
            data["custom_id"] = custom_id
        data.update({
            "color_printing": kwargs.get("color_printing", self._get_config_or_env("COLOR_PRINTING", False)),
            "duplex_printing": kwargs.get("duplex_printing", self._get_config_or_env("DUPLEX_PRINTING", True)),
            "optional_address_sheet": kwargs.get(
                "optional_address_sheet", self._get_config_or_env("OPTIONAL_ADDRESS_SHEET", False)
            ),
            "archiving_duration": self._normalize_archiving_duration(kwargs.get("archiving_duration")),
        })
        sender = kwargs.get("sender", self._get_config_or_env("SENDER_ADDRESS", {}))
        sender_name = sender.get("name")
        sender_address = sender.get("address")
        if sender_address:
            data["sender_address_line_2"] = sender_name
            data["sender_address_line_1"] = sender_address.get("organization")
            data["sender_address_line_3"] = sender_address.get("address_line2")
            data["sender_address_line_4"] = sender_address.get("address_line1")
            data["sender_address_line_5"] = (
                sender_address.get("locality")
                or sender_address.get("po_box")
                or sender_address.get("address_line3")
            )
            data["sender_address_line_6"] = _maileva_address_line_6(
                sender_address, role="sender address"
            )
            _require_maileva_line_1_or_2(
                data["sender_address_line_1"],
                data["sender_address_line_2"],
                role="sender address",
            )
            code = sender_address.get("country_code")
            data["sender_country_code"] = code.upper() if code else code

        if kwargs.get("notification_email"):
            data["notification_email"] = kwargs.get("notification_email", self._get_config_or_env("NOTIFICATION_EMAIL", ""))
            data["notification_types"] = self._get_config_or_env("NOTIFICATION_TYPES", ["ALL_MAILEVA", "ALL_LAPOSTE"])

        if self.is_acknowledgement_of_receipt(**kwargs):
            # registered_mail/v4 — do not send mail/v2-only fields (postage_type, envelope_windows_type, …)
            data["acknowledgement_of_receipt"] = True
            if kwargs.get("returned_mail_scanning", self._get_config_or_env("RETURNED_MAIL_SCANNING", False)):
                data["acknowledgement_of_receipt_scanning"] = True
        else:
            data["print_sender_address"] = kwargs.get(
                "print_sender_address", self._get_config_or_env("PRINT_SENDER_ADDRESS", True)
            )
            data["envelope_windows_type"] = kwargs.get(
                "envelope_windows_type", self._get_config_or_env("ENVELOPE_WINDOWS_TYPE", "DOUBLE")
            )
            priority = kwargs.get("priority")
            postage_type = (
                "urgent"
                if (priority or "").lower() == "urgent"
                else str(self._get_config_or_env("POSTAGE_TYPE", "fast")).lower()
            )
            data["postage_type"] = postage_type.upper()

        if kwargs.get("custom_data") is not None:
            data["custom_data"] = kwargs["custom_data"]
        return data

    def _detail_lre(self, external_id: str) -> dict[str, Any]:
        url = self.get_endpoint('sendings')
        response = self._request("GET", url + "/" + external_id)
        response.raise_for_status()
        return response.json()

    def _create_lre(self, **kwargs: Any) -> dict[str, Any]:
        self.is_acknowledgement_of_receipt(**kwargs)
        if kwargs.get("external_id"):
            return self._detail_lre(kwargs.get("external_id"))
        url = self.get_endpoint('sendings')
        data = self.get_lre_data(**kwargs)
        response = self._request("POST", url, json=data)
        self._raise_for_response(response, f"Maileva create sending failed ({url})")
        return response.json()

    def create_lre(self, **kwargs: Any) -> dict[str, Any]:
        """Create sending and add recipients on the provider (used by prepare_missive)."""
        self.is_acknowledgement_of_receipt(**kwargs)
        response = self._create_lre(**kwargs)
        external_id = response.get("id")
        response["recipients"] = self._add_recipients_lre(kwargs.get("recipients"), external_id)
        return response

    def prepare_lre(self, **kwargs: Any) -> dict[str, Any]:
        """Alias for create_lre (deprecated, use create_lre)."""
        return self.create_lre(**kwargs)

    def update_lre(self, **kwargs: Any) -> dict[str, Any]:
        self.is_acknowledgement_of_receipt(**kwargs)
        response = self._create_lre(**kwargs)
        external_id = response.get("id")
        response["recipients"] = self._add_recipients_lre(kwargs.get("recipients"), external_id)
        return response

    def delete_lre(self, **kwargs: Any) -> dict[str, Any]:
        """DELETE sending on Maileva (draft or submitted); not the same as cancel semantics elsewhere."""
        self.is_acknowledgement_of_receipt(**kwargs)
        url = self.get_endpoint('sendings') + "/" + kwargs.get("external_id")
        response = self._request("DELETE", url)
        return {"code": response.status_code, "message": response.text}

    def _stage_lre_before_submit(self, **kwargs: Any) -> tuple[str, list[Any], list[Any]]:
        """Create/update sending, recipients, and documents; does not call submit."""
        self.is_acknowledgement_of_receipt(**kwargs)
        response = self._create_lre(**kwargs)
        external_id = response.get("id")
        recipients = self._add_recipients_lre(kwargs.get("recipients"), external_id)
        attachments = self._add_attachments_lre(kwargs.get("attachments", []), external_id)
        return external_id, recipients, attachments

    def preview_lre(self, **kwargs: Any) -> dict[str, Any]:
        """Same pipeline as send_lre (sending, recipients, documents) without submit."""
        kwargs = {
            **kwargs,
            "custom_data": kwargs.get("custom_data", "pymissive_temporary_preview"),
        }
        external_id, recipients, attachments = self._stage_lre_before_submit(**kwargs)
        return {
            "id": external_id,
            "event": "draft",
            "code": 200,
            "message": "",
            "event_date": datetime.now(dt_timezone.utc).isoformat(),
            "attachments": attachments,
            "recipients": recipients,
        }

    def send_lre(self, **kwargs: Any) -> dict[str, Any]:
        external_id, recipients, attachments = self._stage_lre_before_submit(**kwargs)
        if is_disable_send():
            return self._disabled_send_response(
                "send_lre",
                external_id=external_id,
                recipients=recipients,
                attachments=attachments,
            )
        url = self.get_endpoint('submit') % external_id
        response = self._request("POST", url)
        response.raise_for_status()
        data = {
            "id": external_id,
            "event": "request",
            "code": response.status_code,
            "message": response.text,
            "event_date": datetime.now(dt_timezone.utc).isoformat(),
            "attachments": attachments,
            "recipients": recipients,
        }
        return data

    #########################################################
    # LRE - Attachments
    #########################################################

    def _add_attachments_lre(self, attachments: list[dict[str, Any]], external_id: str) -> list[dict[str, Any]]:
        external_ids = []
        for priority, attachment in enumerate(attachments, start=1):
            external_ids.append(self.add_attachment_lre(
                attachment=attachment,
                external_id=external_id,
                priority=priority,
            ))
        return external_ids

    def add_attachment_lre(self, **kwargs: Any) -> dict[str, Any]:
        self.is_acknowledgement_of_receipt(**kwargs)
        attachment = kwargs.get("attachment", {})
        external_id = kwargs.get("external_id")
        priority = kwargs.get("priority", 1)
        doc_name = attachment.get("name", "document.pdf")
        content = attachment.get("content", b"")
        url = self.get_endpoint('documents') % external_id
        metadata = {"priority": priority, "name": doc_name, "shrink": True}
        files = {
            'document': (doc_name, content, 'application/pdf'),
            'metadata': ('metadata', json.dumps(metadata), 'application/json'),
        }
        response = self._request("POST", url, files=files, timeout=HTTP_DOCUMENT_TIMEOUT)
        response.raise_for_status()
        response = response.json()
        return {"internal_id": attachment.get("id"), "external_id": response.get("id")}

    def get_attachments_lre(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.is_acknowledgement_of_receipt(**kwargs)
        external_id = kwargs.get("external_id")
        url = self.get_endpoint('documents') % external_id
        response = self._request("GET", url)
        response.raise_for_status()
        return response.json()

    def delete_attachment_lre(self, **kwargs: Any) -> bool:
        self.is_acknowledgement_of_receipt(**kwargs)
        external_id = kwargs.get("external_id")
        document_id = kwargs.get("document_id")
        url = self.get_endpoint('documents') % external_id + "/" + document_id
        response = self._request("DELETE", url)
        response.raise_for_status()
        return True

    #########################################################
    # LRE - Webhooks
    #########################################################

    def create_webhook_lre(self, webhook_data: dict[str, Any]) -> str:
        webhook_url = webhook_data.get("url")
        events = list([event for event in self.events_association.keys() if event.startswith("ON_")])
        resource_types = self.get_resource_types("lre")
        response = self._create_webhook_api(webhook_url, events, resource_types)
        return response

    def _retrieve_webhooks_lre(self) -> list[dict[str, Any]]:
        webhooks = self.retrieve_webhooks()
        resource_types = self.get_resource_types("lre")
        return [
            webhook for webhook in webhooks
            if webhook.get("resource_type") in resource_types
        ]

    def _raw_id_from_webhook_id(self, webhook_id: str | None) -> str | None:
        """Extract raw provider id from normalized webhook_id (e.g. 'maileva-123' -> '123')."""
        if not webhook_id:
            return None
        parts = str(webhook_id).split("-", 1)
        return parts[1] if len(parts) > 1 else parts[0]

    def delete_webhook_lre(self, webhook_data: dict[str, Any]) -> None:
        url = webhook_data.get("url") or webhook_data.get("callback_url")
        if not url:
            raw_id = self._raw_id_from_webhook_id(
                webhook_data.get("webhook_id") or webhook_data.get("id")
            )
            if raw_id:
                for w in self.retrieve_webhooks():
                    if str(w.get("id")) == str(raw_id):
                        url = w.get("callback_url")
                        break
        if not url:
            raise ValueError("Cannot delete webhook: no URL and could not derive from webhook_id")
        return self.delete_webhooks("lre", url)

    def update_webhook_lre(self, webhook_data: dict[str, Any]) -> dict[str, Any]:
        new_url = webhook_data.get("url") or webhook_data.get("callback_url")
        search_url = new_url
        if not search_url:
            raw_id = self._raw_id_from_webhook_id(
                webhook_data.get("webhook_id") or webhook_data.get("id")
            )
            if raw_id:
                for w in self.retrieve_webhooks():
                    if str(w.get("id")) == str(raw_id):
                        search_url = w.get("callback_url")
                        break
        if not search_url:
            raise ValueError("Cannot update webhook: no URL and could not derive from webhook_id")
        return self.update_webhooks("lre", search_url, new_url or search_url)

    #########################################################
    # LRE - Retrieve / Events
    #########################################################

    def get_normalize_events(self, data):
        if "events" in data:
            return data.get("events")
        return None

    def get_normalize_sender_name(self, data: dict[str, Any]) -> str | None:
        name = (data.get("sender_name") or data.get("sender_address_line_2") or "").strip()
        return name or None

    def get_normalize_sender_address(self, data: dict[str, Any]) -> dict[str, str] | None:
        existing = data.get("sender_address")
        if isinstance(existing, dict) and any(
            existing.get(key)
            for key in ("address_line1", "city", "organization", "postal_code")
        ):
            return existing
        return _address_from_maileva_lines(
            data, prefix="sender_", country_key="sender_country_code"
        )

    def get_normalize_recipients(self, data: dict[str, Any]) -> list | None:
        recipients = data.get("recipients")
        if not isinstance(recipients, list):
            return None
        return [
            self._serialize_recipient_ref(
                {
                    "id": rec.get("internal_id") or rec.get("custom_id") or rec.get("id"),
                    "name": rec.get("name"),
                    "address": rec.get("address") if isinstance(rec.get("address"), dict) else None,
                },
                rec,
            )
            if isinstance(rec, dict)
            else rec
            for rec in recipients
        ]

    def _recipient_event_ref(self, recipient: dict[str, Any]) -> dict[str, Any]:
        """Keys Django ``get_recipient`` can match on a retrieved sending.

        Missive identity is the sending ``resource_id``. Do not put Maileva's
        recipient UUID in ``external_id``: that value is not the missive id
        and would steal event-level ``external_id`` if copied upward.
        """
        ref: dict[str, Any] = {}
        if recipient.get("custom_id"):
            ref["id"] = recipient["custom_id"]
            ref["substitute_id"] = recipient["custom_id"]
        name = (recipient.get("address_line_2") or recipient.get("name") or "").strip()
        if name:
            ref["name"] = name
        return ref

    def _serialize_events_lre(self, recipients, detail_lre):
        events = []
        for recipient in recipients:
            recipient_ref = self._recipient_event_ref(recipient)
            if "statuses" in recipient:
                for status in recipient.get("statuses", []):
                    events.append({
                        "resource_id": detail_lre.get("id"),
                        "event": status.get("code"),
                        "event_date": status.get("date"),
                        "recipient": recipient_ref,
                    })
            elif "status" in recipient:
                events.append({
                    "recipient": recipient_ref,
                    "resource_id": detail_lre.get("id"),
                    "event": recipient.get("status"),
                    "event_date": detail_lre.get("submission_date"),
                })
        return events

    def retrieve_lre(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.is_acknowledgement_of_receipt(**kwargs)
        external_id = kwargs.get("external_id")
        detail_lre = self._detail_lre(external_id)
        recipients_lre = self._detail_recipients_lre(external_id)
        result = {
            **detail_lre,
            "events": self._serialize_events_lre(recipients_lre, detail_lre),
            "recipients": [
                self._serialize_recipient_ref({"id": recipient.get("custom_id")}, recipient)
                for recipient in recipients_lre
            ],
        }
        if not result.get("subject") and detail_lre.get("name"):
            result["subject"] = detail_lre["name"]
        sender_name = (detail_lre.get("sender_address_line_2") or "").strip()
        if sender_name and not result.get("sender_name"):
            result["sender_name"] = sender_name
        sender_address = _address_from_maileva_lines(
            detail_lre, prefix="sender_", country_key="sender_country_code"
        )
        if sender_address:
            result["sender_address"] = sender_address
        return result

    def tracking_number_lre(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return carrier tracking numbers for each recipient of a sending.

        Maileva prints the public tracking reference on the deposit-proof PDF
        (domestic: number under ``Numéro de la LR``; international: UPU S10
        under ``NUMERO DE RECOMMANDE``). The recipient API fields are only a
        fallback when no proof is available yet.
        """
        self.is_acknowledgement_of_receipt(**kwargs)
        recipients_lre = self._detail_recipients_lre(kwargs.get("external_id"))
        results = []
        for recipient in recipients_lre:
            ref = self._serialize_recipient_ref({"id": recipient.get("custom_id")}, recipient)
            proof_url = recipient.get("deposit_proof_url")
            if proof_url:
                try:
                    pdf_bytes = self._download_proof_bytes(proof_url)
                    tracking_number = extract_tracking_number_from_deposit_proof(pdf_bytes)
                except Exception:
                    tracking_number = None
                if tracking_number:
                    ref["tracking_number"] = tracking_number
            results.append(ref)
        return results

    #########################################################
    # LRE - Billings
    #########################################################

    @staticmethod
    def _as_billing_date(value: Any) -> str | None:
        if value in (None, ""):
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()[:10]
        return str(value)[:10]

    def _recipient_item_pages(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Paginate ``GET /billing/v1/recipient_items`` (start_index / count)."""
        url = self.get_endpoint("invoice")
        items: list[dict[str, Any]] = []
        start_index = 1
        count = 100
        while True:
            page_params = {
                **params,
                "start_index": start_index,
                "count": count,
            }
            page_params = {
                key: value
                for key, value in page_params.items()
                if value not in (None, "")
            }
            response = self._request("GET", url, params=page_params)
            self._raise_for_response(response, f"Maileva billing failed ({url})")
            data = response.json()
            inv = data.get("invoice")
            page = (
                (inv.get("items") if isinstance(inv, dict) else None)
                or data.get("items")
                or []
            )
            items.extend(page)
            paging = data.get("paging") or {}
            total = paging.get("total_results")
            if not page or len(page) < count:
                break
            if total is not None and len(items) >= int(total):
                break
            start_index += count
        return items

    def _serialize_billing_item(
        self, item: dict[str, Any], *, external_id: Any = None
    ) -> dict[str, Any]:
        user_reference = item.get("user_reference")
        sending_id = item.get("sending_id") or external_id
        recipient_id = item.get("recipient_id")
        recipient_custom_id = item.get("recipient_custom_id")
        recipient = None
        if recipient_id or recipient_custom_id:
            recipient = {}
            if recipient_custom_id:
                recipient["id"] = recipient_custom_id
                recipient["substitute_id"] = recipient_custom_id
            if recipient_id:
                recipient["external_id"] = recipient_id
                recipient.setdefault("id", recipient_id)
        return {
            "external_id": sending_id,
            "substitute_id": user_reference,
            "billing_amount": float(item.get("amount", 0)),
            "estimate_amount": float(item.get("amount", 0)),
            "currency": item.get("currency") or "EUR",
            "invoice": item.get("label", ""),
            "recipient": recipient,
            "raw": item,
        }

    def get_billings_lre(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch invoiced lines from ``/billing/v1/recipient_items``.

        ``user_reference`` is the sending ``custom_id``: ``substitute_id`` when
        set, otherwise the local missive pk. Empty until Maileva invoices.
        """
        if self.is_mode_sandbox():
            return []
        user_reference = _provider_custom_id(kwargs)
        if not user_reference:
            return []
        items = self._recipient_item_pages({"user_reference": user_reference})
        external_id = kwargs.get("external_id")
        return [
            self._serialize_billing_item(item, external_id=external_id)
            for item in items
        ]

    def retrieve_billings(self, start_date, end_date, **kwargs: Any) -> dict[str, Any]:
        """Invoiced recipient lines for a date range via ``recipient_items``.

        Maileva rejects ``start_date`` / ``end_date`` on this resource. The
        documented window is ``start_invoice_date`` / ``end_invoice_date``.
        Downstream ``retrieve_billings`` update-or-creates each row against the
        matching missive (``sending_id`` → ``external_id``, ``user_reference``
        → ``substitute_id``).
        """
        if self.is_mode_sandbox():
            return {"billings": []}
        items = self._recipient_item_pages(
            {
                "start_invoice_date": self._as_billing_date(start_date),
                "end_invoice_date": self._as_billing_date(end_date),
            }
        )
        return {
            "billings": [self._serialize_billing_item(item) for item in items]
        }

    #########################################################
    # LRE - Proofs
    #########################################################

    def retrieve_proofs_lre(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch available proofs from recipients (like Mighty get_prooflist)."""
        self.is_acknowledgement_of_receipt(**kwargs)
        recipients = self._detail_recipients_lre(kwargs.get("external_id"))
        documents = []
        for recipient in recipients:
            for proof in self.proof_keys:
                key = f"{proof}_url"
                if key in recipient:
                    filename = self.normalize_filename(f"{recipient.get('address_line_2')}_{proof}.pdf")
                    documents.append({
                        "filename": filename,
                        "url": recipient.get(key),
                    })
        return documents

    def _download_proof_bytes(self, url: str) -> bytes:
        download_url = self.get_endpoint("proofdownload") % url
        response = self._request(
            "GET", download_url, stream=True, timeout=HTTP_DOCUMENT_TIMEOUT
        )
        response.raise_for_status()
        return response.content

    def download_proof_lre(self, **kwargs: Any) -> bytes:
        self.is_acknowledgement_of_receipt(**kwargs.get("data", {}))
        return self._download_proof_bytes(kwargs.get("url"))

    #########################################################
    # LRE - Webhook handling
    #########################################################

    def handle_webhook_lre(self, payload: dict[str, Any] | bytes) -> dict[str, Any]:
        """Return raw payload for providerkit normalize() via fields_associations."""
        if isinstance(payload, (bytes, bytearray)):
            payload = json.loads(payload.decode("utf-8"))
        return payload

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        """Map Maileva event_type / retrieve status code to a normalized event."""
        return self.events_association.get(
            data.get("event_type") or data.get("event"), "unknown"
        )

    def get_normalize_external_id(self, data: dict[str, Any]) -> str | None:
        """Missive ``external_id`` is the sending id, never the recipient UUID.

        Retrieve events set ``resource_id`` to the sending. Sending-level
        webhooks do the same. Recipient-level webhooks put the recipient
        UUID in ``resource_id``; prefer ``sending_id`` when present.
        """
        detail = data.get("event_detail") if isinstance(data.get("event_detail"), dict) else {}
        sending_id = data.get("sending_id") or detail.get("sending_id")
        if sending_id:
            return str(sending_id)
        resource_name = data.get("resource_name") or ""
        resource_type = data.get("resource_type") or ""
        is_recipient_level = (
            resource_name == "recipients" or str(resource_type).endswith("/recipients")
        )
        if is_recipient_level:
            return None
        if data.get("resource_id"):
            return str(data["resource_id"])
        return None

    def get_normalize_recipient(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Attach the recipient for recipient-scoped LRE events.

        Maileva fires webhooks at two granularities:
        - ``sendings``: the whole sending, with ``resource_custom_id`` set to the
          *sending* custom_id (not a recipient). We return ``None`` so the Django
          layer fans the lifecycle event out to every recipient.
        - ``recipients``: a single recipient, with ``resource_custom_id`` equal to
          the ``custom_id`` we sent when creating the recipient (the Django
          ``MissiveRecipient.substitute_id``). We map it so the event is attached
          directly.

        Retrieve serializes recipient statuses already keyed by that custom_id
        (``recipient.id`` / ``substitute_id``). Keep it, otherwise providerkit
        would overwrite the field with ``None`` and the event would stay
        recipient-less.
        """
        existing = data.get("recipient")
        if isinstance(existing, dict) and (
            existing.get("id") or existing.get("name") or existing.get("external_id")
        ):
            ref: dict[str, Any] = {}
            if existing.get("id"):
                ref["id"] = existing["id"]
            substitute_id = existing.get("substitute_id") or existing.get("id")
            if substitute_id:
                ref["substitute_id"] = substitute_id
            if existing.get("name"):
                ref["name"] = existing["name"]
            return ref
        resource_name = data.get("resource_name") or ""
        resource_type = data.get("resource_type") or ""
        is_recipient_level = (
            resource_name == "recipients" or resource_type.endswith("/recipients")
        )
        if is_recipient_level:
            custom_id = data.get("resource_custom_id")
            if custom_id:
                return {"id": custom_id, "substitute_id": custom_id}
        return None
