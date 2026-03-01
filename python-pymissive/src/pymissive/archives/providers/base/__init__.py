"""Base provider classes and mixins."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ...status import MissiveStatus
from .branded import BaseBrandedMixin
from .common import BaseProviderCommon
from .email import BaseEmailMixin
from .monitoring import BaseMonitoringMixin
from .notification import BaseNotificationMixin
from .postal import BasePostalMixin
from .sms import BaseSMSMixin
from .voice_call import BaseVoiceCallMixin


class BaseProvider(
    BaseProviderCommon,
    BaseEmailMixin,
    BaseSMSMixin,
    BasePostalMixin,
    BaseNotificationMixin,
    BaseVoiceCallMixin,
    BaseMonitoringMixin,
    BaseBrandedMixin,
):
    """Base class combining all mixins for convenience."""

    def _normalize_missive_type(self) -> Optional[str]:
        missive_type = self._get_missive_value("missive_type")
        if missive_type is None:
            return None
        return str(missive_type).upper()

    def _dispatch_by_type(
        self,
        target: Any,
        *,
        missive_type: Optional[str] = None,
        default: Any = None,
        **kwargs: Any,
    ) -> Any:
        """
        Generic dispatch helper.

        `target` can be either:
          - a mapping of normalized missive types to handlers
          - a format string expecting the lower-cased missive type (e.g. "send_%s")
        """
        type_name = (missive_type or self._normalize_missive_type() or "").upper()
        if not type_name:
            return default

        handler: Any
        if isinstance(target, dict):
            handler = target.get(type_name)
        else:
            attr_name = str(target) % type_name.lower()
            handler = getattr(self, attr_name, None)

        if handler is None:
            return default

        return handler(**kwargs) if callable(handler) else handler

    def send(self) -> bool:
        """Send the current missive by dispatching to the appropriate method."""
        if not self.missive:
            return False

        missive_type = self._normalize_missive_type()
        if not missive_type:
            self._update_status(
                MissiveStatus.FAILED, error_message="Missing missive type"
            )
            return False

        if not self.supports(missive_type):
            self._update_status(
                MissiveStatus.FAILED,
                error_message=f"{self.name} does not support {missive_type}",
            )
            return False

        result = self._dispatch_by_type("send_%s", missive_type=missive_type)
        if result is None:
            self._update_status(
                MissiveStatus.FAILED,
                error_message=f"No handler implemented for type {missive_type}",
            )
            return False

        return result if isinstance(result, bool) else False

    def check_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Check delivery status by dispatching to the appropriate method."""
        result = self._dispatch_by_type(
            "check_%s_delivery_status",
            missive_type=kwargs.get("missive_type"),
            default={
                "status": "unknown",
                "error_message": "Missive type not defined or no handler available",
                "details": {},
            },
            **kwargs,
        )

        if isinstance(result, dict):
            return result

        return {
            "status": "unknown",
            "error_message": "No delivery status handler available",
            "details": {},
        }

    def cancel(self) -> bool:
        """Cancel the current missive by dispatching to the appropriate method."""
        if not self.missive or not self._get_missive_value("external_id"):
            return False

        result = self._dispatch_by_type("cancel_%s")
        return result if isinstance(result, bool) else False

    def handle_webhook(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        *,
        missive_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str, Optional[Any]]:
        """Dispatch webhook handling to a type-specific implementation."""
        result = self._dispatch_by_type(
            "handle_%s_webhook",
            missive_type=missive_type,
            payload=payload,
            headers=headers,
            **kwargs,
        )

        if isinstance(result, tuple) and len(result) == 3:
            return result

        type_name = (missive_type or self._normalize_missive_type() or "").upper()
        return (
            False,
            f"No webhook handler available for type '{type_name or 'unknown'}'",
            None,
        )

    def validate_webhook_signature(
        self,
        payload: Any,
        headers: Dict[str, str],
        *,
        missive_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """Dispatch webhook signature validation by missive type."""
        result = self._dispatch_by_type(
            "validate_%s_webhook_signature",
            missive_type=missive_type,
            payload=payload,
            headers=headers,
            **kwargs,
        )

        if isinstance(result, tuple) and len(result) == 2:
            return result

        return True, ""

    def extract_missive_id(
        self,
        payload: Dict[str, Any],
        *,
        missive_type: Optional[str] = None,
    ) -> Optional[str]:
        """Extract a missive identifier from webhook payload by dispatching to type-specific method."""
        result = self._dispatch_by_type(
            "extract_%s_missive_id",
            missive_type=missive_type,
            payload=payload,
        )

        return result if isinstance(result, (str, type(None))) else None

    # calculate_delivery_risk is inherited from BaseProviderCommon


__all__ = [
    "BaseProviderCommon",
    "BaseEmailMixin",
    "BaseSMSMixin",
    "BasePostalMixin",
    "BaseNotificationMixin",
    "BaseVoiceCallMixin",
    "BaseMonitoringMixin",
    "BaseBrandedMixin",
    "BaseProvider",
]
