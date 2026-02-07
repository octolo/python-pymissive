"""Structured address representation with optional backend normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

_ADDRESS_KEYS = (
    "address_line1",
    "address_line2",
    "address_line3",
    "recipient_address_line1",
    "recipient_address_line2",
    "recipient_address_line3",
    "sender_address_line1",
    "sender_address_line2",
    "sender_address_line3",
)


@dataclass(slots=True)
class Address:
    """Lightweight container for structured postal addresses."""

    line1: str = ""
    line2: str = ""
    line3: str = ""
    postal_code: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted: str = ""
    backend_used: Optional[str] = None
    backend_reference: Optional[str] = None
    confidence: Optional[float] = None
    suggestions: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)
    errors: Sequence[str] = field(default_factory=tuple)
    extras: Dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """Return True when no user-level field is populated."""
        return not any(
            [
                self.line1,
                self.line2,
                self.line3,
                self.postal_code,
                self.city,
                self.state,
                self.country,
            ]
        )

    def to_dict(self, *, include_empty: bool = False) -> Dict[str, Any]:
        """Serialize the address to a JSON-friendly dictionary."""
        data = {
            "line1": self.line1,
            "line2": self.line2,
            "line3": self.line3,
            "postal_code": self.postal_code,
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "formatted": self.formatted,
            "backend_used": self.backend_used,
            "backend_reference": self.backend_reference,
            "confidence": self.confidence,
            "suggestions": list(self.suggestions),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "extras": dict(self.extras),
        }
        if not include_empty:
            data = {
                key: value
                for key, value in data.items()
                if value not in ("", None, [], {})
            }
        return data

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "Address":
        """Build an Address instance from a dictionary payload."""
        if not payload:
            return cls()

        def _extract_line(key: str) -> str:
            for alias in (
                key,
                key.replace("line", "_line"),
                f"recipient_{key}",
                f"sender_{key}",
            ):
                if alias in payload and payload[alias]:
                    return str(payload[alias])
            return ""

        return cls(
            line1=_extract_line("line1"),
            line2=_extract_line("line2"),
            line3=_extract_line("line3"),
            postal_code=str(payload.get("postal_code") or payload.get("zip", "")),
            city=str(payload.get("city") or payload.get("town") or ""),
            state=str(payload.get("state") or payload.get("region") or ""),
            country=str(payload.get("country") or payload.get("country_code") or ""),
            latitude=_safe_float(payload.get("latitude")),
            longitude=_safe_float(payload.get("longitude")),
            formatted=str(
                payload.get("formatted_address") or payload.get("formatted") or ""
            ),
            backend_used=payload.get("backend_used") or payload.get("backend"),
            backend_reference=payload.get("backend_reference")
            or payload.get("reference_id")
            or payload.get("address_reference"),
            confidence=_safe_float(payload.get("confidence")),
            suggestions=tuple(payload.get("suggestions") or ()),
            warnings=tuple(payload.get("warnings") or ()),
            errors=tuple(payload.get("errors") or ()),
            extras=_extract_extras(payload),
        )

    def merge(self, other: "Address", *, prefer_other: bool = True) -> "Address":
        """Merge two addresses, optionally preferring `other` values when provided."""

        def _select(current: Any, new_value: Any) -> Any:
            if prefer_other and new_value not in ("", None):
                return new_value
            if not prefer_other and current not in ("", None):
                return current
            return new_value if new_value not in ("", None) else current

        merged = Address(
            line1=_select(self.line1, other.line1),
            line2=_select(self.line2, other.line2),
            line3=_select(self.line3, other.line3),
            postal_code=_select(self.postal_code, other.postal_code),
            city=_select(self.city, other.city),
            state=_select(self.state, other.state),
            country=_select(self.country, other.country),
            latitude=_select(self.latitude, other.latitude),
            longitude=_select(self.longitude, other.longitude),
            formatted=_select(self.formatted, other.formatted),
            backend_used=other.backend_used or self.backend_used,
            backend_reference=other.backend_reference or self.backend_reference,
            confidence=_select(self.confidence, other.confidence),
            suggestions=other.suggestions or self.suggestions,
            warnings=other.warnings or self.warnings,
            errors=other.errors or self.errors,
            extras={**self.extras, **other.extras},
        )
        return merged

    @classmethod
    def normalize_with_backends(
        cls,
        backends_config: Sequence[Dict[str, Any]] | None,
        *,
        operation: str = "validate",
        min_confidence: Optional[float] = None,
        **address_kwargs: Any,
    ) -> Tuple["Address", Dict[str, Any]]:
        """Call configured backends and return a normalized Address plus raw payload."""
        if not backends_config:
            return cls.from_dict(address_kwargs), {
                "error": "No address backends configured"
            }

        from .helpers import search_addresses

        # Build query string from address components
        address_parts = [
            address_kwargs.get("address_line1"),
            address_kwargs.get("address_line2"),
            address_kwargs.get("address_line3"),
            address_kwargs.get("postal_code"),
            address_kwargs.get("city"),
            address_kwargs.get("state"),
        ]
        query = ", ".join(filter(None, address_parts)) or ""

        # If query is empty but we have components, try a simpler query
        if not query:
            query = address_kwargs.get("address_line1") or ""

        search_result = search_addresses(
            backends_config=backends_config,
            query=query,
            country=address_kwargs.get("country"),
            min_confidence=min_confidence,
            limit=1,
        )

        # Get first result or use error payload
        results = search_result.get("results", [])
        if results:
            payload = results[0]
            normalized_block = payload.get("normalized_address") or payload
        else:
            payload = search_result
            normalized_block = {}
        normalized = cls.from_dict(
            {
                **address_kwargs,
                **_flatten_address_dict(normalized_block),
                "backend_used": payload.get("backend_used"),
                "confidence": payload.get("confidence"),
                "warnings": payload.get("warnings"),
                "errors": payload.get("errors"),
                "suggestions": payload.get("suggestions"),
                "backend_reference": payload.get("backend_reference")
                or payload.get("reference_id")
                or payload.get("address_reference"),
            }
        )
        return normalized, payload


def _extract_extras(payload: Mapping[str, Any]) -> Dict[str, Any]:
    extras = dict(payload.get("extras") or {})
    for key in ("latitude", "longitude", "formatted_address"):
        if key in payload and key not in extras:
            extras[key] = payload[key]
    for key in _ADDRESS_KEYS:
        if key in payload and payload[key]:
            extras.setdefault(key, payload[key])
    return extras


def _flatten_address_dict(payload: Mapping[str, Any]) -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key in ("line1", "line2", "line3", "postal_code", "city", "state", "country"):
        if key in payload and payload[key]:
            flat[key] = payload[key]
    suffixes = (
        "line1",
        "line2",
        "line3",
        "postal_code",
        "city",
        "state",
        "country",
    )
    for key in _ADDRESS_KEYS:
        value = payload.get(key)
        if value and key.endswith(suffixes):
            alias = key.split("_")[-1]
            flat.setdefault(alias, value)
    if "formatted_address" in payload and payload["formatted_address"]:
        flat["formatted"] = payload["formatted_address"]
    if "latitude" in payload:
        flat["latitude"] = payload.get("latitude")
    if "longitude" in payload:
        flat["longitude"] = payload.get("longitude")
    if "backend_reference" in payload and payload["backend_reference"]:
        flat["backend_reference"] = payload["backend_reference"]
    elif "address_reference" in payload and payload["address_reference"]:
        flat["backend_reference"] = payload["address_reference"]
    return flat


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
