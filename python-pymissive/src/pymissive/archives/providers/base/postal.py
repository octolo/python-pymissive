"""Postal provider mixin without Django dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ...status import MissiveStatus
from ._attachments import AttachmentMimeTypeMixin

POSTAL_SERVICE_VARIANTS = [
    "postal",
    "postal_registered",
    "postal_signature",
    "lre",
    "lre_qualified",
    "ere",
]

POSTAL_SERVICE_FIELDS = [
    "price",
    "archiving_duration",
    "page_limit",
    "allowed_attachment_mime_types",
    "allowed_page_formats",
    "color_printing_available",
    "duplex_printing_available",
    "page_price_color",
    "page_price_black_white",
    "page_price_single_sided",
    "page_price_duplex",
    "envelope_limits",
    "geographic_coverage",
]

BASE_POSTAL_DEFAULTS = {
    "page_limit": 50,
    "allowed_attachment_mime_types": [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ],
    "allowed_page_formats": ["A4", "Letter", "Legal", "A3"],
    "color_printing_available": True,
    "duplex_printing_available": True,
    "price": 0.0,
    "archiving_duration": 0,
    "page_price_color": 0.0,
    "page_price_black_white": 0.0,
    "page_price_single_sided": 0.0,
    "page_price_duplex": 0.0,
    "envelope_limits": [],
    "geographic_coverage": ["*"],
}


class BasePostalMixin(AttachmentMimeTypeMixin):
    """Postal mail-specific functionality mixin."""

    # auto-populate service attributes and config field lists
    for _variant in POSTAL_SERVICE_VARIANTS:
        prefix = f"{_variant}_"
        defaults = BASE_POSTAL_DEFAULTS if _variant == "postal" else None
        for field in POSTAL_SERVICE_FIELDS:
            attr_name = f"{prefix}{field}"
            locals()[attr_name] = defaults.get(field) if defaults is not None else None
        config_fields_attr = f"{prefix}config_fields"
        config_fields_list: list[str] = []
        for field in POSTAL_SERVICE_FIELDS:
            config_fields_list.append(f"{prefix}{field}")
        locals()[config_fields_attr] = config_fields_list
        legacy_alias = f"{prefix}geo"
        locals()[legacy_alias] = locals().get(f"{prefix}geographic_coverage")

    def _get_postal_service_value(self, service: str, field: str) -> Any:
        """Return configuration value for the given service, with postal fallback."""
        normalized = (service or "postal").strip().lower()
        attr_name = f"{normalized}_{field}"
        if normalized != "postal" and hasattr(self, attr_name):
            value = getattr(self, attr_name)
            if value is not None:
                return value
        base_attr = f"postal_{field}"
        return getattr(self, base_attr, None)

    def _build_service_info_payload(self, service: str) -> Dict[str, Any]:
        """Construct generic service info payload from service-specific config."""
        archiving_duration = self._get_postal_service_value(
            service, "archiving_duration"
        )
        envelope_limits = self._get_postal_service_value(service, "envelope_limits")
        color_available = self._get_postal_service_value(
            service, "color_printing_available"
        )
        duplex_available = self._get_postal_service_value(
            service, "duplex_printing_available"
        )
        page_limit = self._get_postal_service_value(service, "page_limit")
        mime_types = self._get_postal_service_value(
            service, "allowed_attachment_mime_types"
        )
        page_formats = self._get_postal_service_value(service, "allowed_page_formats")

        return {
            "credits": None,
            "credits_type": "amount",
            "is_available": None,
            "limits": {
                "archiving_duration_days": archiving_duration,
                "envelope_limits": envelope_limits,
                "page_limit": page_limit,
                "allowed_attachment_mime_types": mime_types,
                "allowed_page_formats": page_formats,
            },
            "warnings": ["service info not overridden for %s" % service],
            "options": [],
            "details": {
                "color_printing_available": color_available,
                "duplex_printing_available": duplex_available,
                "geographic_coverage": self._get_postal_service_value(
                    service, "geographic_coverage"
                ),
            },
        }

    def get_postal_service_info(self) -> Dict[str, Any]:
        """Return postal service information. Override in subclasses."""
        info = self._build_service_info_payload("postal")
        info["warnings"] = [
            "get_postal_service_info() method not implemented for this provider"
        ]
        return info

    def get_postal_registered_service_info(self) -> Dict[str, Any]:
        """Registered mail info delegates to postal info unless overridden."""
        info = self._build_service_info_payload("postal_registered")
        info["warnings"] = [
            "get_postal_registered_service_info() method not implemented for this provider"
        ]
        return info

    def get_postal_signature_service_info(self) -> Dict[str, Any]:
        """Signature-required mail info delegates to registered info."""
        info = self._build_service_info_payload("postal_signature")
        info["warnings"] = [
            "get_postal_signature_service_info() method not implemented for this provider"
        ]
        return info

    def get_lre_service_info(self) -> Dict[str, Any]:
        """LRE service info placeholder."""
        info = self._build_service_info_payload("lre")
        info["warnings"] = ["get_lre_service_info() method not implemented"]
        return info

    def get_lre_qualified_service_info(self) -> Dict[str, Any]:
        """Qualified LRE info placeholder."""
        info = self._build_service_info_payload("lre_qualified")
        info["warnings"] = ["get_lre_qualified_service_info() method not implemented"]
        return info

    def get_ere_service_info(self) -> Dict[str, Any]:
        """Electronic registered email info placeholder."""
        info = self._build_service_info_payload("ere")
        info["warnings"] = ["get_ere_service_info() method not implemented"]
        return info

    def check_postal_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Check postal delivery status. Override in subclasses."""
        return {
            "status": "unknown",
            "delivered_at": None,
            "tracking_events": [],
            "signature_proof": None,
            "error_code": None,
            "error_message": "check_postal_delivery_status() method not implemented for this provider",
            "details": {},
        }

    def check_postal_registered_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Delegates to postal status unless overridden."""
        return self.check_postal_delivery_status(**kwargs)

    def check_postal_signature_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Delegates to registered status unless overridden."""
        return self.check_postal_registered_delivery_status(**kwargs)

    def check_lre_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Placeholder for LRE status."""
        return {
            "status": "unknown",
            "error_message": "check_lre_delivery_status() method not implemented",
            "details": {},
        }

    def check_lre_qualified_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Delegates to LRE status unless overridden."""
        return self.check_lre_delivery_status(**kwargs)

    def check_ere_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Placeholder for ERE status."""
        return {
            "status": "unknown",
            "error_message": "check_ere_delivery_status() method not implemented",
            "details": {},
        }

    def _send_postal_service(
        self,
        *,
        service: str,
        is_registered: bool = False,
        requires_signature: bool = False,
        **kwargs,
    ) -> bool:
        """Subclasses must implement the concrete postal delivery."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _send_postal_service()."
        )

    def _require_postal_address(self) -> bool:
        recipient_address = self._get_missive_value("get_recipient_address") or self._get_missive_value(
            "recipient_address"
        )
        if not recipient_address:
            self._update_status(MissiveStatus.FAILED, error_message="No postal address")
            return False
        return True

    def send_postal(self, **kwargs) -> bool:
        """Default implementation delegating to `_send_postal_service`."""
        if not self._require_postal_address():
            return False
        return self._send_postal_service(service="postal", **kwargs)

    def send_postal_registered(self, **kwargs) -> bool:
        """Registered mail defaults to postal handler with specific flags."""
        if not self._require_postal_address():
            return False
        return self._send_postal_service(
            service="postal_registered", is_registered=True, **kwargs
        )

    def send_postal_signature(self, **kwargs) -> bool:
        """Signature-required mail defaults to registered handler."""
        if not self._require_postal_address():
            return False
        return self._send_postal_service(
            service="postal_signature",
            is_registered=True,
            requires_signature=True,
            **kwargs,
        )

    def send_lre(self, **kwargs) -> bool:
        """LRE sending placeholder."""
        raise NotImplementedError(f"{self.name} must implement the send_lre() method")

    def send_lre_qualified(self, **kwargs) -> bool:
        """Qualified LRE defaults to LRE handler."""
        return self.send_lre(**kwargs)

    def send_ere(self, **kwargs) -> bool:
        """Electronic registered email placeholder."""
        raise NotImplementedError(f"{self.name} must implement the send_ere() method")

    def validate_postal_address(self, address: str) -> Dict[str, Any]:
        """Validate a postal address and return basic heuristics."""
        warnings: List[str] = []
        parsed: Dict[str, Any] = {}

        lines = [line.strip() for line in address.split("\n") if line.strip()]

        if len(lines) < 3:
            warnings.append("Address too short (at least 3 lines expected)")

        is_complete = len(lines) >= 3 and not warnings

        return {
            "is_valid": bool(lines),
            "is_complete": is_complete,
            "warnings": warnings,
            "parsed": parsed,
        }

    def calculate_postal_cost(
        self,
        weight_grams: int = 20,
        is_registered: bool = False,
        international: bool = False,
        service: str = "postal",
    ) -> Dict[str, Any]:
        """Estimate the cost of a postal mail."""
        configured_price = self._get_postal_service_value(service, "price")
        delivery_days = 2
        if configured_price is not None:
            base_cost = configured_price
        else:
            if international:
                base_cost = 1.96
                delivery_days = 7
            else:
                if weight_grams <= 20:
                    base_cost = 1.29
                    delivery_days = 2
                elif weight_grams <= 100:
                    base_cost = 1.96
                    delivery_days = 1
                else:
                    base_cost = 3.15
                    delivery_days = 2

            if is_registered:
                base_cost += 4.50

        return {
            "cost": base_cost,
            "format": service,
            "delivery_days": delivery_days,
            "weight_grams": weight_grams,
        }

    def calculate_postal_registered_cost(
        self, weight_grams: int = 20, international: bool = False
    ) -> Dict[str, Any]:
        """Registered postal cost helper."""
        return self.calculate_postal_cost(
            weight_grams=weight_grams,
            international=international,
            is_registered=True,
            service="postal_registered",
        )

    def calculate_postal_signature_cost(
        self, weight_grams: int = 20, international: bool = False
    ) -> Dict[str, Any]:
        """Signature-required postal cost helper."""
        return self.calculate_postal_cost(
            weight_grams=weight_grams,
            international=international,
            is_registered=True,
            service="postal_signature",
        )

    def calculate_lre_cost(self) -> Dict[str, Any]:
        """Cost helper for electronic registered letters."""
        price = self._get_postal_service_value("lre", "price") or 0.0
        return {"cost": price, "format": "lre"}

    def calculate_lre_qualified_cost(self) -> Dict[str, Any]:
        """Cost helper for qualified LRE."""
        price = self._get_postal_service_value("lre_qualified", "price")
        if price is None:
            price = self._get_postal_service_value("lre", "price") or 0.0
        return {"cost": price, "format": "lre_qualified"}

    def calculate_ere_cost(self) -> Dict[str, Any]:
        """Cost helper for electronic registered email."""
        price = self._get_postal_service_value("ere", "price") or 0.0
        return {"cost": price, "format": "ere"}

    def _build_service_status_payload(
        self,
        *,
        rate_limits: Dict[str, Any],
        warnings: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
        sla: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Default service status helper shared by postal providers."""
        clock = getattr(self, "_clock", None)
        last_check = clock() if callable(clock) else datetime.now(timezone.utc)
        return {
            "status": "unknown",
            "is_available": None,
            "services": self._get_services(),
            "credits": {
                "type": "money",
                "remaining": None,
                "currency": "EUR",
                "limit": None,
                "percentage": None,
            },
            "rate_limits": rate_limits,
            "sla": sla or {"uptime_percentage": 99.0},
            "last_check": last_check,
            "warnings": warnings or [],
            "details": details or {},
        }

    def _prepare_attachments_for_service(
        self, attachments: List[Any], service: str
    ) -> List[Dict[str, Any]]:
        """Generic attachment preparation helper."""
        prepared: List[Dict[str, Any]] = []

        allowed_mimes = self._get_postal_service_value(
            service, "allowed_attachment_mime_types"
        )
        allowed_formats = [
            fmt.upper()
            for fmt in (
                self._get_postal_service_value(service, "allowed_page_formats") or []
            )
        ]
        page_limit = self._get_postal_service_value(service, "page_limit")

        for idx, attachment in enumerate(attachments):
            mime_type = getattr(attachment, "mime_type", None)
            if mime_type and allowed_mimes and mime_type not in allowed_mimes:
                raise ValueError(
                    f"{service} attachment {idx + 1}: MIME type '{mime_type}' not allowed."
                )

            page_format = getattr(attachment, "page_format", None)
            if (
                page_format
                and allowed_formats
                and page_format.upper() not in allowed_formats
            ):
                raise ValueError(
                    f"{service} attachment {idx + 1}: Page format '{page_format}' not allowed."
                )

            page_count = getattr(attachment, "page_count", None)
            if page_count is not None:
                try:
                    page_count_int = int(page_count)
                    if page_limit and page_count_int > page_limit:
                        raise ValueError(
                            f"{service} attachment {idx + 1}: "
                            f"{page_count_int} pages exceeds maximum of {page_limit} pages"
                        )
                except (ValueError, TypeError) as exc:
                    raise ValueError(
                        f"{service} attachment {idx + 1}: Invalid page_count value"
                    ) from exc

            file_info = {
                "filename": getattr(attachment, "filename", None),
                "order": getattr(attachment, "order", None),
                "mime_type": mime_type,
                "url": getattr(attachment, "file_url", None),
                "page_count": getattr(attachment, "page_count", None),
                "page_format": page_format,
                "service": service,
            }
            prepared.append(file_info)

        return prepared

    def prepare_postal_attachments(
        self, attachments: List[Any]
    ) -> List[Dict[str, Any]]:
        """Prepare attachments for postal delivery."""
        return self._prepare_attachments_for_service(attachments, "postal")

    def prepare_postal_registered_attachments(
        self, attachments: List[Any]
    ) -> List[Dict[str, Any]]:
        """Prepare attachments for registered postal delivery."""
        return self._prepare_attachments_for_service(attachments, "postal_registered")

    def prepare_postal_signature_attachments(
        self, attachments: List[Any]
    ) -> List[Dict[str, Any]]:
        """Prepare attachments for signature-required postal delivery."""
        return self._prepare_attachments_for_service(attachments, "postal_signature")

    def prepare_lre_attachments(self, attachments: List[Any]) -> List[Dict[str, Any]]:
        """Prepare attachments for LRE delivery."""
        return self._prepare_attachments_for_service(attachments, "lre")

    def prepare_lre_qualified_attachments(
        self, attachments: List[Any]
    ) -> List[Dict[str, Any]]:
        """Prepare attachments for qualified LRE delivery."""
        return self._prepare_attachments_for_service(attachments, "lre_qualified")

    def prepare_ere_attachments(self, attachments: List[Any]) -> List[Dict[str, Any]]:
        """Prepare attachments for ERE delivery."""
        return self._prepare_attachments_for_service(attachments, "ere")

    def _check_attachment_page_count(
        self, attachment: Any, idx: int
    ) -> tuple[Optional[int], List[str], List[str]]:
        """Check page count for a single attachment."""
        errors: List[str] = []
        warnings: List[str] = []

        page_count = getattr(attachment, "page_count", None)
        if page_count is not None:
            try:
                page_count = int(page_count)
                if page_count > self.max_postal_pages:
                    errors.append(
                        f"Attachment {idx + 1}: {page_count} pages exceeds maximum "
                        f"of {self.max_postal_pages} pages"
                    )
                return page_count, errors, warnings
            except (ValueError, TypeError):
                warnings.append(f"Attachment {idx + 1}: Invalid page_count value")

        return None, errors, warnings

    def _check_attachment_page_format(
        self, attachment: Any, idx: int
    ) -> tuple[List[str], List[str]]:
        """Check page format for a single attachment."""
        errors: List[str] = []
        warnings: List[str] = []

        page_format = getattr(attachment, "page_format", None)
        if (
            page_format
            and self.allowed_page_formats
            and page_format.upper()
            not in [fmt.upper() for fmt in self.allowed_page_formats]
        ):
            errors.append(
                f"Attachment {idx + 1}: Page format '{page_format}' not allowed. "
                f"Allowed formats: {', '.join(self.allowed_page_formats)}"
            )

        return errors, warnings

    def check_attachments(self, attachments: List[Any]) -> Dict[str, Any]:
        """
        Validate postal attachments against size, MIME type, page count, and page format limits.

        Args:
            attachments: List of attachment objects with attributes like:
                - mime_type: MIME type of the file
                - page_count: Number of pages (for documents)
                - page_format: Page format (e.g., "A4", "Letter")
                - size_bytes: File size in bytes (optional)

        Returns:
            Dict with validation results:
                - is_valid: bool
                - errors: List[str] of error messages
                - warnings: List[str] of warning messages
                - details: Dict with per-attachment validation details
        """
        errors: List[str] = []
        warnings: List[str] = []
        details: Dict[str, Any] = {
            "total_pages": 0,
            "attachments_checked": 0,
            "attachments_valid": 0,
        }

        if not attachments:
            return {
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "details": details,
            }

        total_pages = 0

        for idx, attachment in enumerate(attachments):
            attachment_errors: List[str] = []
            attachment_warnings: List[str] = []

            # Check MIME type
            mime_errors, mime_warnings = self._check_attachment_mime_type(
                attachment, idx
            )
            attachment_errors.extend(mime_errors)
            attachment_warnings.extend(mime_warnings)

            # Check page count
            page_count, page_errors, page_warnings = self._check_attachment_page_count(
                attachment, idx
            )
            attachment_errors.extend(page_errors)
            attachment_warnings.extend(page_warnings)

            if page_count is not None:
                total_pages += page_count

            # Check page format
            format_errors, format_warnings = self._check_attachment_page_format(
                attachment, idx
            )
            attachment_errors.extend(format_errors)
            attachment_warnings.extend(format_warnings)

            if attachment_errors:
                errors.extend(attachment_errors)
            if attachment_warnings:
                warnings.extend(attachment_warnings)

            details["attachments_checked"] += 1
            if not attachment_errors:
                details["attachments_valid"] += 1

        # Check total pages across all attachments
        details["total_pages"] = total_pages
        if total_pages > self.max_postal_pages:
            errors.append(
                f"Total pages ({total_pages}) exceeds maximum of {self.max_postal_pages} pages"
            )

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "details": details,
        }

    def cancel_postal(self, **kwargs) -> bool:
        """Cancel a scheduled postal missive (override in subclasses)."""
        return False

    def cancel_postal_registered(self, **kwargs) -> bool:
        """Registered cancel defaults to postal cancel."""
        return self.cancel_postal(**kwargs)

    def cancel_postal_signature(self, **kwargs) -> bool:
        """Signature cancel defaults to registered cancel."""
        return self.cancel_postal_registered(**kwargs)

    def cancel_lre(self, **kwargs) -> bool:
        """Placeholder for LRE cancel."""
        return False

    def cancel_lre_qualified(self, **kwargs) -> bool:
        """Qualified LRE cancel defaults to LRE cancel."""
        return self.cancel_lre(**kwargs)

    def cancel_ere(self, **kwargs) -> bool:
        """Placeholder for ERE cancel."""
        return False

    def validate_postal_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Validate postal webhook signature. Override in subclasses."""
        return True, ""

    def validate_postal_registered_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Registered webhook signature defaults to postal."""
        return self.validate_postal_webhook_signature(payload, headers)

    def validate_postal_signature_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Signature webhook validation defaults to registered."""
        return self.validate_postal_registered_webhook_signature(payload, headers)

    def validate_lre_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Placeholder for LRE webhook signature validation."""
        return True, ""

    def validate_lre_qualified_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Qualified LRE webhook validation defaults to LRE."""
        return self.validate_lre_webhook_signature(payload, headers)

    def validate_ere_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Placeholder for ERE webhook signature validation."""
        return True, ""

    def handle_postal_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Process postal webhook payload. Override in subclasses."""
        return (
            False,
            "handle_postal_webhook() method not implemented for this provider",
            None,
        )

    def handle_postal_registered_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Registered webhook defaults to postal handler."""
        return self.handle_postal_webhook(payload, headers)

    def handle_postal_signature_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Signature webhook defaults to registered handler."""
        return self.handle_postal_registered_webhook(payload, headers)

    def handle_lre_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Placeholder for LRE webhook handler."""
        return False, "handle_lre_webhook() method not implemented", None

    def handle_lre_qualified_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Qualified LRE webhook defaults to LRE handler."""
        return self.handle_lre_webhook(payload, headers)

    def handle_ere_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Placeholder for ERE webhook handler."""
        return False, "handle_ere_webhook() method not implemented", None

    def extract_postal_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """Extract missive ID from postal webhook payload. Override in subclasses."""
        return None

    def extract_postal_registered_missive_id(
        self, payload: Dict[str, Any]
    ) -> Optional[str]:
        """Registered missive ID defaults to postal extractor."""
        return self.extract_postal_missive_id(payload)

    def extract_postal_signature_missive_id(
        self, payload: Dict[str, Any]
    ) -> Optional[str]:
        """Signature missive ID defaults to registered extractor."""
        return self.extract_postal_registered_missive_id(payload)

    def extract_lre_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """Placeholder for LRE missive ID extractor."""
        return None

    def extract_lre_qualified_missive_id(
        self, payload: Dict[str, Any]
    ) -> Optional[str]:
        """Qualified LRE missive ID defaults to LRE extractor."""
        return self.extract_lre_missive_id(payload)

    def extract_ere_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """Placeholder for ERE missive ID extractor."""
        return None
