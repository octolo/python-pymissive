from typing import Any
from pymissive.config import MISSIVE_ACKNOWLEDGEMENT_LEVELS


class AcknowledgementMixin:
    """Mixin providing acknowledgement levels configuration."""
    available_acknowledgement_levels = MISSIVE_ACKNOWLEDGEMENT_LEVELS