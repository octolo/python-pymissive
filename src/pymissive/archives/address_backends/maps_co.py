"""Maps.co Geocoding API address verification backend."""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Dict, Optional

from .base import BaseAddressBackend


class MapsCoAddressBackend(BaseAddressBackend):
    """Maps.co Geocoding API backend for address verification.

    Maps.co provides forward and reverse geocoding based on OpenStreetMap data
    using the Nominatim geocoding engine.
    Free tier: Limited requests/day (check documentation).
    Requires API key (free registration).
    """

    name = "maps_co"
    display_name = "Maps.co"
    config_keys = ["MAPS_CO_API_KEY", "MAPS_CO_BASE_URL"]
    required_packages = ["requests"]
    documentation_url = "https://geocode.maps.co/docs/"
    site_url = "https://geocode.maps.co"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Maps.co backend.

        Args:
            config: Optional configuration dict with:
                - MAPS_CO_API_KEY: API key (required)
                - MAPS_CO_BASE_URL: Custom base URL (default: official)
        """
        super().__init__(config)
        self._api_key = self._config.get("MAPS_CO_API_KEY")
        if not self._api_key:
            raise ValueError("MAPS_CO_API_KEY is required")
        self._base_url = self._config.get("MAPS_CO_BASE_URL", "https://geocode.maps.co")
        self._last_request_time = 0.0

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Make a request to the Maps.co API."""
        self._rate_limit_with_interval("_last_request_time", 1.0)

        default_params: Dict[str, Any] = {"api_key": self._api_key, "format": "json"}
        return self._request_json(
            self._base_url,
            endpoint,
            params,
            default_params=default_params,
        )

    def _extract_address_from_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from a Maps.co API result."""
        address = result.get("address", {})

        # Build address_line1 from house_number and road
        address_line1_parts = []
        if address.get("house_number"):
            address_line1_parts.append(str(address["house_number"]))
        if address.get("road"):
            address_line1_parts.append(address["road"])
        address_line1 = " ".join(address_line1_parts).strip()

        # Fallback to display_name if address_line1 is empty
        if not address_line1:
            display_name = result.get("display_name", "")
            if display_name:
                parts = display_name.split(",")
                if parts:
                    address_line1 = parts[0].strip()

        # Extract coordinates
        latitude = None
        longitude = None
        if "lat" in result and result["lat"]:
            with suppress(ValueError, TypeError):
                latitude = float(result["lat"])
        if "lon" in result and result["lon"]:
            with suppress(ValueError, TypeError):
                longitude = float(result["lon"])

        return {
            "address_line1": address_line1 or "",
            "address_line2": address.get("suburb", "") or address.get("neighbourhood", ""),
            "address_line3": address.get("quarter", ""),
            "city": (
                address.get("city", "")
                or address.get("town", "")
                or address.get("village", "")
                or address.get("municipality", "")
            ),
            "postal_code": address.get("postcode", ""),
            "state": address.get("state", "") or address.get("region", ""),
            "country": (
                address.get("country_code", "").upper() if address.get("country_code") else ""
            ),
            "address_reference": (
                str(result.get("place_id", "")) if result.get("place_id") else None
            ),
            "latitude": latitude,
            "longitude": longitude,
            "confidence": (
                0.8 if result.get("place_id") else 0.5
            ),  # Maps.co doesn't provide explicit confidence
        }

    def validate_address(
        self,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        address_line3: Optional[str] = None,
        city: Optional[str] = None,
        postal_code: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
        query: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Validate an address using Maps.co search API."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        params: Dict[str, Any] = {"q": query_string, "limit": 5}
        if country:
            params["country"] = country.upper()

        result = self._make_request("/search", params)

        if isinstance(result, dict) and "error" in result:
            return self._build_validation_failure(error=result["error"])

        features = result if isinstance(result, list) else []

        def _extract_feature(item: Dict[str, Any]) -> Dict[str, Any]:
            payload = self._extract_address_from_result(item)
            payload["formatted_address"] = item.get("display_name", "")
            return payload

        return self._feature_validation_payload(
            features=features,
            extractor=_extract_feature,
            formatted_getter=lambda item: item.get("display_name", ""),
            confidence_getter=lambda _item, normalized: normalized.get("confidence", 0.0),
            suggestion_formatter=lambda item, normalized: {
                "formatted_address": item.get("display_name", ""),
                "confidence": normalized.get("confidence", 0.0),
                "latitude": normalized.get("latitude"),
                "longitude": normalized.get("longitude"),
            },
            valid_threshold=0.5,
            warning_threshold=0.7,
            missing_error="No address found",
            max_suggestions=4,
        )

    def geocode(
        self,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        address_line3: Optional[str] = None,
        city: Optional[str] = None,
        postal_code: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
        query: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Geocode an address to coordinates using Maps.co."""

        def _request(query_string: str) -> Dict[str, Any]:
            params: Dict[str, Any] = {"q": query_string, "limit": 1}
            if country:
                params["country"] = country.upper()
            return self._make_request("/search", params)  # type: ignore[no-any-return]

        def _handle(result: Dict[str, Any], _query: str) -> Dict[str, Any]:
            features: list[Dict[str, Any]] = result if isinstance(result, list) else []

            def _extract_feature(item: Dict[str, Any]) -> Dict[str, Any]:
                payload = self._extract_address_from_result(item)
                payload["formatted_address"] = item.get("display_name", "")
                return payload

            return self._feature_geocode_payload(
                features=features,
                extractor=_extract_feature,
                formatted_getter=lambda item: item.get("display_name", ""),
                accuracy_getter=lambda _item, _normalized: "ROOFTOP",
                confidence_getter=lambda _item, normalized: normalized.get("confidence", 0.0),
                missing_error="No address found",
            )

        return self._execute_geocode_flow(
            query=query,
            context=locals(),
            failure_builder=self._build_geocode_failure,
            request_callable=_request,
            result_handler=_handle,
        )

    def reverse_geocode(self, latitude: float, longitude: float, **kwargs: Any) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address using Maps.co."""
        params: Dict[str, Any] = {"lat": latitude, "lon": longitude}
        if "language" in kwargs:
            params["accept-language"] = kwargs["language"]

        result = self._make_request("/reverse", params)

        if "error" in result:
            payload = self._build_empty_address_payload(error=result["error"])
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            payload["address_reference"] = None
            return payload

        if not result or not isinstance(result, dict):
            payload = self._build_empty_address_payload(
                error="Invalid response format"
            )
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            payload["address_reference"] = None
            return payload

        normalized = self._extract_address_from_result(result)

        return {
            **normalized,
            "formatted_address": result.get("display_name", ""),
            "latitude": normalized.get("latitude", latitude),
            "longitude": normalized.get("longitude", longitude),
            "confidence": normalized.get("confidence", 0.0),
            "address_reference": normalized.get("address_reference"),
            "errors": [],
        }

    def get_address_by_reference(self, address_reference: str, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve address details by a reference ID using Maps.co.

        Maps.co uses Nominatim place_id for references.
        """
        return self._build_empty_address_payload(
            address_reference=address_reference,
            error=(
                "Maps.co API does not support direct lookup by place_id. "
                "Use reverse geocoding with coordinates instead."
            ),
        )
