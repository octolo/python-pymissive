"""Simple missive object for framework-agnostic messaging."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from .status import MissiveStatus


@dataclass
class Missive:
    """Lightweight missive object for sending messages via providers."""

    missive_type: str
    body: str
    subject: Optional[str] = None
    body_text: Optional[str] = None

    # Recipient information
    recipient_email: Optional[str] = None
    recipient_phone: Optional[str] = None
    recipient: Optional[Any] = None  # For complex recipients with metadata

    # Status tracking
    status: Optional[MissiveStatus] = field(default=None)
    external_id: Optional[str] = None
    error_message: Optional[str] = None
    provider: Optional[str] = None

    # Timestamps
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None

    # Options
    provider_options: Optional[Dict[str, Any]] = field(default_factory=dict)
    is_registered: bool = False
    requires_signature: bool = False

    # Internal tracking
    _id: Optional[int] = None

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.status is None:
            self.status = MissiveStatus.DRAFT
        if self.body_text is None:
            self.body_text = self.body

    @property
    def id(self) -> Optional[int]:
        """Return missive ID (for compatibility with Django models)."""
        return self._id

    def save(self) -> None:
        """Placeholder for save method (for compatibility with Django models)."""
        # In a framework-agnostic context, this is a no-op
        # Subclasses or wrappers can override this

    def can_send(self) -> bool:
        """Check if missive can be sent."""
        return self.status in (MissiveStatus.DRAFT, MissiveStatus.PENDING)
