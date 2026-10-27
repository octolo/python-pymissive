import json
import re
import zlib
from typing import Any

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


def _http_error_reason_parts(payload) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return [
        value.strip()
        for key in _HTTP_ERROR_REASON_KEYS
        if isinstance((value := payload.get(key)), str) and value.strip()
    ]


def _http_error_item_part(item) -> str:
    if not isinstance(item, dict):
        return ""
    field = str(item.get("field") or item.get("path") or "").strip()
    message = str(item.get("message") or item.get("code") or item.get("error") or "").strip()
    return ": ".join(piece for piece in (field, message) if piece)


def _http_error_parts(payload) -> list[str]:
    parts = _http_error_reason_parts(payload)
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list):
        parts.extend(filter(None, (_http_error_item_part(item) for item in errors[:8])))
    return list(dict.fromkeys(parts))


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
    summary = " — ".join(_http_error_parts(payload))
    if len(summary) > limit:
        return summary[: limit - 3] + "..."
    return summary


#: Envelope window. mail/v3 and registered_mail/v4 use the same placement.
_ADDRESS_OFFSET = {
    "top": "20mm",
    "width": "70mm",
    "height": "30mm",
}

#: Maileva product → (API mode, version). Chosen by the service, not acknowledgement.
_POSTAL_API = {
    "letter": ("mail", "v3"),
    "registered_letter": ("registered_mail", "v4"),
}


def _postal_api(product: str) -> tuple[str, str]:
    """Return ``(postal_mode, version)`` for a Maileva product. Raises if unknown."""
    try:
        return _POSTAL_API[product]
    except KeyError:
        raise ValueError(f"Unknown Maileva postal product: {product!r}") from None


def _registered_acknowledgement_of_receipt(kwargs: dict[str, Any]) -> bool:
    """``registered_mail/v4`` AR flag. Default True when the caller omitted it."""
    if "acknowledgement_of_receipt" in kwargs:
        return bool(kwargs["acknowledgement_of_receipt"])
    ack = kwargs.get("acknowledgement")
    if ack is None or ack == "":
        return True
    if isinstance(ack, bool):
        return ack
    return str(ack).strip().lower() != "basic_delivery"


# International registered mail (UPU S10), e.g. RW799210633FR.
_UPU_S10_RE = re.compile(r"\b[A-Z]{2}\d{9}[A-Z]{2}\b")
# Domestic La Poste LR number printed under "Numéro de la LR" (13 or 15 digits).
_FR_LR_RE = re.compile(r"(?<!\d)(\d{15}|\d{13})(?!\d)")


_MAILEVA_PO_BOX_RE = re.compile(
    r"^(?:BP|CS|TSA|B\.?\s*P\.?|BO[IÎ]TE\s*POSTALE)\b",
    re.IGNORECASE,
)


def _notification_email(**kwargs: Any) -> str:
    """Maileva accepts a single progress-alert email.

    An explicit ``notification_email`` string wins (additional_config / callers).
    Otherwise the first email on ``notification`` recipients is used.
    """
    explicit = kwargs.get("notification_email")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    for recipient in kwargs.get("notification") or []:
        if not isinstance(recipient, dict):
            continue
        email = (recipient.get("email") or "").strip()
        if email:
            return email
    return ""


def _provider_custom_id(data: dict[str, Any] | None) -> str | None:
    """Maileva ``custom_id`` is the client substitute_id, else the local id."""
    if not data:
        return None
    value = data.get("substitute_id") or data.get("id")
    if value in (None, ""):
        return None
    return str(value)


def _billing_page_params(params: dict[str, Any], start_index: int, count: int) -> dict[str, Any]:
    values = {**params, "start_index": start_index, "count": count}
    return {key: value for key, value in values.items() if value not in (None, "")}


def _billing_page_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    invoice = data.get("invoice")
    invoice_items = invoice.get("items") if isinstance(invoice, dict) else None
    return invoice_items or data.get("items") or []


def _billing_page_is_last(data, page, item_count, count) -> bool:
    if not page or len(page) < count:
        return True
    total = (data.get("paging") or {}).get("total_results")
    return total is not None and item_count >= int(total)


def _existing_recipient_ref(existing) -> dict[str, Any] | None:
    if not isinstance(existing, dict):
        return None
    if not (existing.get("id") or existing.get("name") or existing.get("external_id")):
        return None
    ref: dict[str, Any] = {}
    if existing.get("id"):
        ref["id"] = existing["id"]
    substitute_id = existing.get("substitute_id") or existing.get("id")
    if substitute_id:
        ref["substitute_id"] = substitute_id
    if existing.get("name"):
        ref["name"] = existing["name"]
    return ref


def _is_recipient_resource(data: dict[str, Any]) -> bool:
    resource_name = data.get("resource_name") or ""
    resource_type = data.get("resource_type") or ""
    return resource_name == "recipients" or resource_type.endswith("/recipients")


def _is_maileva_country_prefix(token: str) -> bool:
    return bool(token) and token.isalpha() and 1 <= len(token) <= 3


def _maileva_postal_start(tokens: list[str]) -> tuple[int, bool]:
    international = (
        len(tokens) >= 2
        and _is_maileva_country_prefix(tokens[0])
        and any(character.isdigit() for character in tokens[1])
    )
    return (1 if international else 0), international


def _strip_repeated_postal_prefix(rest: list[str], postal_code: str) -> tuple[list[str], bool]:
    repeated = len(rest) >= 2 and _is_maileva_country_prefix(rest[0]) and rest[1] == postal_code
    return (rest[2:], True) if repeated else (rest, False)


def _strip_maileva_country(rest: list[str], international: bool) -> list[str]:
    if international and rest and rest[-1].isalpha() and len(rest[-1]) > 2:
        return rest[:-1]
    return rest


def _pop_maileva_state(rest: list[str]) -> tuple[list[str], str]:
    if rest and len(rest[-1]) == 2 and rest[-1].isalpha():
        return rest[:-1], rest[-1].upper()
    return rest, ""


def _split_maileva_cedex(rest: list[str]) -> tuple[list[str], str]:
    cedex_at = next(
        (index for index, token in enumerate(rest) if token.upper() == "CEDEX"),
        None,
    )
    if cedex_at is None:
        return rest, ""
    return rest[:cedex_at], " ".join(rest[cedex_at:])


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
    postal_at, international = _maileva_postal_start(tokens)
    if postal_at < len(tokens) and any(character.isdigit() for character in tokens[postal_at]):
        result["postal_code"] = tokens[postal_at]
        postal_at += 1
    rest, repeated = _strip_repeated_postal_prefix(tokens[postal_at:], result.get("postal_code", ""))
    rest = _strip_maileva_country(rest, international or repeated)
    rest, state_code = _pop_maileva_state(rest)
    rest, sorting_code = _split_maileva_cedex(rest)
    if state_code:
        result["state_code"] = state_code
    if sorting_code:
        result["sorting_code"] = sorting_code
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
    for match in re.finditer(rb"(?<![A-Za-z])stream\r?\n", pdf_bytes):
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


def _pdf_hex_width(hexstr: str, mapping: dict[int, str]) -> int:
    preferred_width = 4 if mapping and max(mapping, default=0) > 255 else 2
    widths = [width for width in (2, 4) if len(hexstr) % width == 0]
    if mapping and len(widths) > 1:
        return max(
            widths,
            key=lambda candidate: (
                sum(int(hexstr[index : index + candidate], 16) in mapping for index in range(0, len(hexstr), candidate))
                / (len(hexstr) / candidate),
                candidate == preferred_width,
            ),
        )
    return preferred_width if preferred_width in widths else widths[0]


def _pdf_decode_hex_tj(hexstr: str, mapping: dict[int, str]) -> str:
    if not hexstr or len(hexstr) % 2:
        return ""
    width = _pdf_hex_width(hexstr, mapping)
    chars = []
    for i in range(0, len(hexstr), width):
        code = int(hexstr[i : i + width], 16)
        chars.append(mapping.get(code, chr(code) if code < 256 else ""))
    return "".join(chars)


def _extract_deposit_proof_text(pdf_bytes: bytes) -> str:
    streams = list(_iter_pdf_streams(pdf_bytes))
    mapping = _pdf_tounicode_map(streams)
    parts: list[str] = []
    for stream in streams:
        for match in re.finditer(rb"\((?:\\.|[^\\)])*\)\s*Tj", stream):
            inner = match.group(0)
            inner = inner[1 : inner.rfind(b")")]
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


__all__ = [
    "_TOKEN_REFRESH_SKEW",
    "_HTTP_ERROR_REASON_KEYS",
    "_http_error_reason_parts",
    "_http_error_item_part",
    "_http_error_parts",
    "_compact_http_error_detail",
    "_ADDRESS_OFFSET",
    "_POSTAL_API",
    "_postal_api",
    "_registered_acknowledgement_of_receipt",
    "_UPU_S10_RE",
    "_FR_LR_RE",
    "_MAILEVA_PO_BOX_RE",
    "_notification_email",
    "_provider_custom_id",
    "_billing_page_params",
    "_billing_page_items",
    "_billing_page_is_last",
    "_existing_recipient_ref",
    "_is_recipient_resource",
    "_is_maileva_country_prefix",
    "_maileva_postal_start",
    "_strip_repeated_postal_prefix",
    "_strip_maileva_country",
    "_pop_maileva_state",
    "_split_maileva_cedex",
    "_geoaddress_from_maileva_line_5",
    "_require_maileva_line_1_or_2",
    "_maileva_address_line_6",
    "_parse_maileva_address_line_6",
    "_address_from_maileva_lines",
    "_inflate_pdf_stream",
    "_iter_pdf_streams",
    "_pdf_tounicode_map",
    "_pdf_unescape_literal",
    "_pdf_decode_hex_tj",
    "_extract_deposit_proof_text",
    "extract_tracking_number_from_deposit_proof",
]
