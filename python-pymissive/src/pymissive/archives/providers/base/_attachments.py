"""Shared helpers for provider attachment validation."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


class AttachmentMimeTypeMixin:
    """Provide MIME-type and size validation logic for provider attachments."""

    allowed_attachment_mime_types: List[str]

    def _check_attachment_mime_type(
        self, attachment: Any, idx: int, **kwargs: Any
    ) -> Tuple[List[str], List[str]]:
        """Check MIME type for a single attachment."""
        errors: List[str] = []
        warnings: List[str] = []

        mime_type = getattr(attachment, "mime_type", None)
        if mime_type:
            allowed_types = kwargs.get("allowed_types", self.allowed_attachment_mime_types)
            if allowed_types and mime_type not in allowed_types:
                errors.append(
                    f"Attachment {idx + 1}: MIME type '{mime_type}' not allowed. "
                    f"Allowed types: {', '.join(allowed_types)}"
                )
        else:
            warnings.append(f"Attachment {idx + 1}: MIME type not specified")

        return errors, warnings

    def _get_attachment_size(self, attachment: Any) -> Optional[int]:
        """Get attachment size in bytes, trying multiple methods."""
        size_bytes = getattr(attachment, "size_bytes", None)
        if size_bytes is not None:
            return size_bytes

        file_obj = getattr(attachment, "file", None)
        if file_obj and hasattr(file_obj, "read"):
            try:
                current_pos = file_obj.tell() if hasattr(file_obj, "tell") else 0
                file_obj.seek(0, 2)
                size_bytes = file_obj.tell() if hasattr(file_obj, "tell") else None
                file_obj.seek(current_pos)
                return size_bytes
            except Exception:
                return None
        return None

    def _check_attachment_size(
        self, attachment: Any, idx: int, max_size_bytes: int
    ) -> Tuple[Optional[int], List[str], List[str]]:
        """Check file size for a single attachment."""
        errors: List[str] = []
        warnings: List[str] = []

        size_bytes = self._get_attachment_size(attachment)
        if size_bytes is not None:
            try:
                size_bytes = int(size_bytes)
                if size_bytes > max_size_bytes:
                    size_mb = size_bytes / (1024 * 1024)
                    max_mb = max_size_bytes / (1024 * 1024)
                    errors.append(
                        f"Attachment {idx + 1}: Size {size_mb:.2f} MB exceeds maximum "
                        f"of {max_mb:.2f} MB"
                    )
                return size_bytes, errors, warnings
            except (ValueError, TypeError):
                warnings.append(f"Attachment {idx + 1}: Invalid size_bytes value")
        else:
            warnings.append(f"Attachment {idx + 1}: File size not specified")

        return None, errors, warnings


def aggregate_attachment_checks(
    attachments: List[Any],
    *,
    mime_checker: Callable[[Any, int], Tuple[List[str], List[str]]],
    size_checker: Callable[[Any, int], Tuple[Optional[int], List[str], List[str]]],
    details_factory: Optional[Callable[[], Dict[str, Any]]] = None,
) -> Tuple[List[str], List[str], Dict[str, Any], int]:
    """Run MIME/size validations and aggregate errors, warnings, and totals."""
    errors: List[str] = []
    warnings: List[str] = []
    details: Dict[str, Any] = (
        details_factory()
        if details_factory
        else {"total_size_bytes": 0, "attachments_checked": 0, "attachments_valid": 0}
    )
    total_size_bytes = 0

    for idx, attachment in enumerate(attachments):
        attachment_errors: List[str] = []
        attachment_warnings: List[str] = []

        mime_errors, mime_warnings = mime_checker(attachment, idx)
        attachment_errors.extend(mime_errors)
        attachment_warnings.extend(mime_warnings)

        size_bytes, size_errors, size_warnings = size_checker(attachment, idx)
        attachment_errors.extend(size_errors)
        attachment_warnings.extend(size_warnings)

        if size_bytes is not None:
            total_size_bytes += size_bytes

        if attachment_errors:
            errors.extend(attachment_errors)
        if attachment_warnings:
            warnings.extend(attachment_warnings)

        details["attachments_checked"] = details.get("attachments_checked", 0) + 1
        if not attachment_errors:
            details["attachments_valid"] = details.get("attachments_valid", 0) + 1

    details["total_size_bytes"] = total_size_bytes
    return errors, warnings, details, total_size_bytes


def summarize_attachment_validation(
    *,
    attachments: List[Any],
    mime_checker: Callable[[Any, int], Tuple[List[str], List[str]]],
    size_checker: Callable[[Any, int], Tuple[Optional[int], List[str], List[str]]],
    max_size_bytes: int,
    max_size_mb: float,
    size_error_template: str,
    details_factory: Optional[Callable[[], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Validate attachments and build a standardized response."""
    errors, warnings, details, total_size_bytes = aggregate_attachment_checks(
        attachments,
        mime_checker=mime_checker,
        size_checker=size_checker,
        details_factory=details_factory,
    )

    if total_size_bytes > max_size_bytes:
        total_size_mb = total_size_bytes / (1024 * 1024)
        errors.append(
            size_error_template.format(total_mb=total_size_mb, max_mb=max_size_mb)
        )

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "details": details,
    }


def attachment_check_empty_result() -> Dict[str, Any]:
    """Return a standardized payload when no attachments are provided."""
    return {
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "details": {
            "total_size_bytes": 0,
            "attachments_checked": 0,
            "attachments_valid": 0,
        },
    }
