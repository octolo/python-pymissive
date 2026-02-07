"""Common status definitions reused by providers."""

from __future__ import annotations

from enum import Enum


class MissiveStatus(str, Enum):
    """Simplified status values inspired by django-missive."""

    DRAFT = "DRAFT"
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @classmethod
    def terminal_states(cls) -> tuple["MissiveStatus", ...]:
        """Return states that are considered final."""
        return cls.DELIVERED, cls.READ, cls.FAILED, cls.CANCELLED
