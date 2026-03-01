"""Generic mixin for app messaging providers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ...status import MissiveStatus
from ._attachments import (
    AttachmentMimeTypeMixin,
    attachment_check_empty_result,
    summarize_attachment_validation,
)

BRANDED_DEFAULTS: Dict[str, Any] = {
    "archiving_duration": 0,
    "max_attachment_size_mb": 20,
    "allowed_attachment_mime_types": [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "audio/mpeg",
        "audio/mp3",
        "audio/ogg",
        "audio/wav",
        "video/mp4",
        "video/quicktime",
        "video/x-msvideo",
    ],
    "geographic_coverage": ["*"],
}


class BaseBrandedMixin(AttachmentMimeTypeMixin):
    """Generic mixin for messaging platforms (WhatsApp, Slack, etc.)."""

    branded_archiving_duration: int = BRANDED_DEFAULTS["archiving_duration"]
    branded_max_attachment_size_mb: int = BRANDED_DEFAULTS["max_attachment_size_mb"]
    branded_allowed_attachment_mime_types: list[str] = BRANDED_DEFAULTS[
        "allowed_attachment_mime_types"
    ]
    branded_geographic_coverage: list[str] | str = BRANDED_DEFAULTS[
        "geographic_coverage"
    ]
    branded_geo = branded_geographic_coverage

    brand_specific_config_fields: Dict[str, List[str]] = {}

    @property
    def max_attachment_size_bytes(self) -> int:
        """Return max attachment size in bytes."""
        return int(self.branded_max_attachment_size_mb * 1024 * 1024)

    def send_branded(self, brand_name: Optional[str] = None, **kwargs) -> bool:
        """Send a branded message by dispatching to send_{brand_name}."""
        target_name = brand_name or getattr(self, "name", None)

        if not target_name:
            self._update_status(
                MissiveStatus.FAILED,
                error_message="Provider name or brand_name missing",
            )
            return False

        method_name = f"send_{str(target_name).lower()}"

        # Security: method_name is constructed from target_name which comes from
        # brand_name parameter or self.name (both are provider names, not user input)
        # and is prefixed with "send_", so it's safe to use with getattr
        if not hasattr(self, method_name):
            self._update_status(
                MissiveStatus.FAILED,
                error_message=f"{method_name}() method not implemented for this provider",
            )
            return False

        return getattr(self, method_name)(**kwargs)

    def _get_brand_config(self, brand_name: str) -> Dict[str, Any]:
        """Return config overrides for a given brand from class attributes."""
        overrides: Dict[str, Any] = {}
        normalized = brand_name.lower()
        for field in BRANDED_DEFAULTS.keys():
            attr_name = f"{normalized}_{field}"
            overrides[field] = getattr(self, attr_name, BRANDED_DEFAULTS[field])
        return overrides

    def get_branded_service_info(
        self, brand_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return service information for a branded provider."""
        target_name = brand_name or getattr(self, "name", None)

        if not target_name:
            return {
                "credits": None,
                "is_available": None,
                "limits": {
                    "archiving_duration_days": self.branded_archiving_duration,
                },
                "warnings": ["Provider name or brand_name missing"],
                "details": {},
            }

        normalized = str(target_name).lower()
        method_name = f"get_{normalized}_service_info"

        if hasattr(self, method_name):
            return getattr(self, method_name)()

        config = self._get_brand_config(normalized)
        return {
            "credits": None,
            "is_available": None,
            "limits": {
                "archiving_duration_days": config["archiving_duration"],
                "max_attachment_size_mb": config["max_attachment_size_mb"],
                "allowed_attachment_mime_types": config[
                    "allowed_attachment_mime_types"
                ],
            },
            "warnings": [f"{method_name}() method not implemented for this provider"],
            "details": {
                "geographic_coverage": config.get(
                    "geographic_coverage", self.branded_geographic_coverage
                ),
            },
        }

    def check_branded_delivery_status(
        self, brand_name: Optional[str] = None, **kwargs
    ) -> Dict[str, Any]:
        """Check delivery status for a branded provider."""
        target_name = brand_name or getattr(self, "name", None)

        if not target_name:
            return {
                "status": "unknown",
                "delivered_at": None,
                "read_at": None,
                "error_code": None,
                "error_message": "Provider name or brand_name missing",
                "details": {},
            }

        normalized = str(target_name).lower()
        method_name = f"check_{normalized}_delivery_status"

        if hasattr(self, method_name):
            return getattr(self, method_name)(**kwargs)

        return {
            "status": "unknown",
            "delivered_at": None,
            "read_at": None,
            "error_code": None,
            "error_message": f"{method_name}() method not implemented",
            "details": {},
        }

    def _get_organization_context(self) -> Optional[Dict[str, Any]]:
        """Return relevant organization context from missive metadata."""
        metadata = getattr(self.missive, "metadata", {}) if self.missive else {}
        if not metadata:
            return None

        context_keys = {
            "workspace_id",
            "team_id",
            "channel_id",
            "organization_id",
            "server_id",
            "guild_id",
            "chat_id",
        }

        context = {key: metadata[key] for key in context_keys if key in metadata}
        return context or None

    def cancel_branded(self, brand_name: Optional[str] = None, **kwargs) -> bool:
        """Cancel a branded message."""
        target_name = brand_name or getattr(self, "name", None)

        if not target_name:
            return False

        method_name = f"cancel_{str(target_name).lower()}"
        if hasattr(self, method_name):
            return getattr(self, method_name)(**kwargs)

        return False

    def validate_branded_webhook_signature(
        self, payload: Any, headers: Dict[str, str], brand_name: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Validate branded webhook signature by dispatching to brand-specific method."""
        target_name = brand_name or getattr(self, "name", None)
        if not target_name:
            return True, ""

        method_name = f"validate_{str(target_name).lower()}_webhook_signature"
        if hasattr(self, method_name):
            return getattr(self, method_name)(payload, headers)

        return True, ""

    def handle_branded_webhook(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        brand_name: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Any]]:
        """Process branded webhook by dispatching to brand-specific method."""
        target_name = brand_name or getattr(self, "name", None)
        if not target_name:
            return False, "Provider name or brand_name missing", None

        method_name = f"handle_{str(target_name).lower()}_webhook"
        if hasattr(self, method_name):
            return getattr(self, method_name)(payload, headers)

        return False, f"{method_name}() method not implemented", None

    def extract_branded_missive_id(
        self, payload: Dict[str, Any], brand_name: Optional[str] = None
    ) -> Optional[str]:
        """Extract missive ID from branded webhook by dispatching to brand-specific method."""
        target_name = brand_name or getattr(self, "name", None)
        if not target_name:
            return None

        method_name = f"extract_{str(target_name).lower()}_missive_id"
        if hasattr(self, method_name):
            return getattr(self, method_name)(payload)

        return None

    def _check_attachment_mime_type(
        self, attachment: Any, idx: int, *, brand_name: Optional[str] = None
    ) -> tuple[List[str], List[str]]:
        """Check MIME type for a single attachment."""
        errors: List[str] = []
        warnings: List[str] = []

        target_name = brand_name or getattr(self, "name", None)
        normalized = (target_name or "").lower()
        allowed_mimes = self._get_brand_config(normalized)[
            "allowed_attachment_mime_types"
        ]

        mime_type = getattr(attachment, "mime_type", None)
        if mime_type:
            if allowed_mimes and mime_type not in allowed_mimes:
                errors.append(
                    f"Attachment {idx + 1}: MIME type '{mime_type}' not allowed. "
                    f"Allowed types: {', '.join(allowed_mimes)}"
                )
        else:
            warnings.append(f"Attachment {idx + 1}: MIME type not specified")

        return errors, warnings

    def check_attachments(
        self, attachments: List[Any], brand_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate branded attachments against size and MIME type limits.

        Args:
            attachments: List of attachment objects with attributes like:
                - mime_type: MIME type of the file
                - size_bytes: File size in bytes
                - file: File object with read() method (optional)

        Returns:
            Dict with validation results:
                - is_valid: bool
                - errors: List[str] of error messages
                - warnings: List[str] of warning messages
                - details: Dict with per-attachment validation details
        """
        if not attachments:
            return attachment_check_empty_result()

        target_name = brand_name or getattr(self, "name", None)
        normalized = (target_name or "").lower()
        brand_config = self._get_brand_config(normalized)
        max_size_mb = float(brand_config["max_attachment_size_mb"])
        max_size_bytes = int(max_size_mb * 1024 * 1024)

        return summarize_attachment_validation(
            attachments=attachments,
            mime_checker=lambda attachment, idx: self._check_attachment_mime_type(
                attachment,
                idx,
                allowed_types=brand_config["allowed_attachment_mime_types"],
            ),
            size_checker=lambda attachment, idx: self._check_attachment_size(
                attachment, idx, max_size_bytes
            ),
            max_size_bytes=max_size_bytes,
            max_size_mb=max_size_mb,
            size_error_template=(
                "Total attachment size ({total_mb:.2f} MB) exceeds maximum of {max_mb:.2f} MB"
            ),
            details_factory=lambda: {
                "total_size_bytes": 0,
                "attachments_checked": 0,
                "attachments_valid": 0,
            },
        )

    def prepare_branded_attachments(
        self, attachments: List[Any]
    ) -> List[Dict[str, Any]]:
        """Prepare attachments for branded messaging platforms."""
        prepared: List[Dict[str, Any]] = []

        for attachment in attachments:
            file_content: Optional[bytes] = None
            file_obj = getattr(attachment, "file", None)
            if file_obj and hasattr(file_obj, "read"):
                try:
                    file_content = file_obj.read()
                except Exception:  # pragma: no cover - defensive
                    file_content = None

            file_info = {
                "filename": getattr(attachment, "filename", None),
                "content": file_content,
                "url": getattr(attachment, "external_url", None),
                "mime_type": getattr(attachment, "mime_type", None),
                "caption": getattr(attachment, "caption", None),
            }
            prepared.append(file_info)

        return prepared
