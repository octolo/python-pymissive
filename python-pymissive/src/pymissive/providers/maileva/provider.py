import logging

import requests

from pymissive.utils import is_disable_send
from ..base import MissiveProviderBase
from .api import MailevaApiMixin
from .helpers import (
    _TOKEN_REFRESH_SKEW,
    _HTTP_ERROR_REASON_KEYS,
    _http_error_reason_parts,
    _http_error_item_part,
    _http_error_parts,
    _compact_http_error_detail,
    _ADDRESS_OFFSET,
    _POSTAL_API,
    _postal_api,
    _registered_acknowledgement_of_receipt,
    _UPU_S10_RE,
    _FR_LR_RE,
    _MAILEVA_PO_BOX_RE,
    _notification_email,
    _provider_custom_id,
    _billing_page_params,
    _billing_page_items,
    _billing_page_is_last,
    _existing_recipient_ref,
    _is_recipient_resource,
    _is_maileva_country_prefix,
    _maileva_postal_start,
    _strip_repeated_postal_prefix,
    _strip_maileva_country,
    _pop_maileva_state,
    _split_maileva_cedex,
    _geoaddress_from_maileva_line_5,
    _require_maileva_line_1_or_2,
    _maileva_address_line_6,
    _parse_maileva_address_line_6,
    _address_from_maileva_lines,
    _inflate_pdf_stream,
    _iter_pdf_streams,
    _pdf_tounicode_map,
    _pdf_unescape_literal,
    _pdf_decode_hex_tj,
    _extract_deposit_proof_text,
    extract_tracking_number_from_deposit_proof,
)
from .retrieve import MailevaRetrieveMixin
from .send import MailevaSendMixin
from .webhooks import MailevaWebhookMixin

logger = logging.getLogger(__name__)

__all__ = [
    "MailevaProvider",
    "_ADDRESS_OFFSET",
    "_FR_LR_RE",
    "_HTTP_ERROR_REASON_KEYS",
    "_MAILEVA_PO_BOX_RE",
    "_POSTAL_API",
    "_TOKEN_REFRESH_SKEW",
    "_UPU_S10_RE",
    "_address_from_maileva_lines",
    "_billing_page_is_last",
    "_billing_page_items",
    "_billing_page_params",
    "_compact_http_error_detail",
    "_existing_recipient_ref",
    "_extract_deposit_proof_text",
    "_geoaddress_from_maileva_line_5",
    "_http_error_item_part",
    "_http_error_parts",
    "_http_error_reason_parts",
    "_inflate_pdf_stream",
    "_is_maileva_country_prefix",
    "_is_recipient_resource",
    "_iter_pdf_streams",
    "_maileva_address_line_6",
    "_maileva_postal_start",
    "_notification_email",
    "_parse_maileva_address_line_6",
    "_pdf_decode_hex_tj",
    "_pdf_tounicode_map",
    "_pdf_unescape_literal",
    "_pop_maileva_state",
    "_postal_api",
    "_provider_custom_id",
    "_registered_acknowledgement_of_receipt",
    "_require_maileva_line_1_or_2",
    "_split_maileva_cedex",
    "_strip_maileva_country",
    "_strip_repeated_postal_prefix",
    "extract_tracking_number_from_deposit_proof",
    "requests",
]


class MailevaProvider(
    MailevaApiMixin,
    MailevaSendMixin,
    MailevaWebhookMixin,
    MailevaRetrieveMixin,
    MissiveProviderBase,
):
    """Maileva provider (electronic simple letter and registered letter)."""

    name = "maileva"
    display_name = "Maileva"
    description = "Simple letter and electronic registered letter (registered letter)"
    required_packages = ["requests"]
    config_keys = [
        "CLIENTID",
        "SECRET",
        "USERNAME",
        "PASSWORD",
        "SANDBOX",
        "WEBHOOK_SECRET",
        "WEBHOOK_BASIC_LOGIN",
        "ARCHIVING_DURATION",
        "PRINT_SENDER_ADDRESS",
        "DUPLEX_PRINTING",
        "COLOR_PRINTING",
        "POSTAGE_TYPE",
    ]
    AUTH_URL_SANDBOX = "https://connexion.sandbox.maileva.net"
    AUTH_URL = "https://connexion.maileva.com"
    config_defaults = {
        "SANDBOX": False,
        "ARCHIVING_DURATION": 3,
        "PRINT_SENDER_ADDRESS": True,
        "DUPLEX_PRINTING": True,
        "COLOR_PRINTING": False,
        "POSTAGE_TYPE": "FAST",
        "WEBHOOK_BASIC_LOGIN": "pymissive",
        "BASE_URL_SANDBOX": "https://api.sandbox.maileva.net",
        "BASE_URL": "https://api.maileva.com",
        "BASE_TOKEN_URL_SANDBOX": AUTH_URL_SANDBOX,
        "BASE_TOKEN_URL": AUTH_URL,
    }
    endpoints = {
        "auth": "{base_url}/auth/realms/services/protocol/openid-connect/token",
        "sendings": "{base_url}/{postal_mode}/{version}/sendings",
        "documents": "{base_url}/{postal_mode}/{version}/sendings/%s/documents",
        "recipients": "{base_url}/{postal_mode}/{version}/sendings/%s/recipients",
        "submit": "{base_url}/{postal_mode}/{version}/sendings/%s/submit",
        "delete": "{base_url}/{postal_mode}/{version}/sendings/%s",
        "prooflist": "{base_url}/{postal_mode}/{version}/global_deposit_proofs?sending_id=%s",
        "proof": "{base_url}/{postal_mode}/{version}/global_deposit_proofs/%s",
        "proofdownload": "{base_url}/{postal_mode}/{version}%s",
        "invoice": "{base_url}/billing/v1/recipient_items",
        "subscriptions": "{base_url}/notification_center/v2/subscriptions",
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
        "registered_mail/v4/sendings": "registered_letter",
        "registered_mail/v4/recipients": "registered_letter",
        "registered_mail/v2/sendings": "registered_letter",
        "registered_mail/v2/recipients": "registered_letter",
        "mail/v3/sendings": "letter",
        "mail/v3/recipients": "letter",
        "mail/v2/sendings": "letter",
        "mail/v2/recipients": "letter",
    }
    proof_keys = [
        "content_proof_embedded_document",
        "deposit_proof",
        "content_proof",
        "archive",
    ]
    registered_letter_proof_keys = [
        *proof_keys,
        "acknowledgement_of_receipt",
    ]

    def _is_send_disabled(self) -> bool:
        return is_disable_send()
