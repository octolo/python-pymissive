"""Geocode Earth API address verification backend."""

from __future__ import annotations

from typing import Any, Dict, Optional


from .base import BaseAddressBackend
from .pelias_mixin import PeliasFeatureMixin


class GeocodeEarthAddressBackend(PeliasFeatureMixin, BaseAddressBackend):
    """Geocode Earth Geocoding API backend for address verification.

    Geocode Earth is a Pelias-based geocoding service.
    Uses the /autocomplete endpoint for optimized address suggestions.
    Free tier: Limited requests/day (check documentation).
    Requires API key (free registration).
    """

    name = "geocode_earth"
    display_name = "Geocode Earth"
    config_keys = ["GEOCODE_EARTH_API_KEY", "GEOCODE_EARTH_BASE_URL"]
    required_packages = ["requests"]
    documentation_url = "https://geocode.earth/docs"
    site_url = "https://geocode.earth"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Geocode Earth backend.

        Args:
            config: Optional configuration dict with:
                - GEOCODE_EARTH_API_KEY: API key (required)
                - GEOCODE_EARTH_BASE_URL: Custom base URL (default: official)
        """
        super().__init__(config)
        self._api_key = self._config.get("GEOCODE_EARTH_API_KEY")
        if not self._api_key:
            raise ValueError("GEOCODE_EARTH_API_KEY is required")
        self._base_url = self._config.get("GEOCODE_EARTH_BASE_URL", "https://api.geocode.earth/v1")
        self._last_request_time = 0.0

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the Geocode Earth API."""
        self._rate_limit_with_interval("_last_request_time", 0.5)

        default_params: Dict[str, Any] = {"api_key": self._api_key}
        return self._request_json(
            self._base_url,
            endpoint,
            params,
            default_params=default_params,
        )

    def _extract_address_from_feature(self, feature: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from a Geocode Earth/Pelias feature."""
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})

        # Build address_line1 from housenumber and street
        address_line1_parts = []
        if properties.get("housenumber"):
            address_line1_parts.append(properties["housenumber"])
        if properties.get("street"):
            address_line1_parts.append(properties["street"])
        address_line1 = " ".join(address_line1_parts).strip()

        # Fallback to name if address_line1 is empty
        if not address_line1:
            address_line1 = properties.get("name", "")

        # Extract coordinates (GeoJSON format: [longitude, latitude])
        coordinates = geometry.get("coordinates", [])
        longitude = None
        latitude = None
        if len(coordinates) >= 2:
            longitude = float(coordinates[0])
            latitude = float(coordinates[1])

        return {
            "address_line1": address_line1 or "",
            "address_line2": properties.get("neighbourhood", ""),
            "address_line3": properties.get("borough", ""),
            "city": properties.get("locality", "")
            or properties.get("localadmin", "")
            or properties.get("county", ""),
            "postal_code": properties.get("postalcode", ""),
            "state": properties.get("region", ""),
            "country": (
                properties.get("country_a", "").upper() if properties.get("country_a") else ""
            ),
            "address_reference": properties.get("gid") or feature.get("id"),
            "latitude": latitude,
            "longitude": longitude,
            "confidence": float(properties.get("confidence", 0.0)),
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
        """Validate an address using Geocode Earth autocomplete API."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        params: Dict[str, Any] = {"text": query_string, "size": 5}
        if country:
            params["boundary.country"] = country.upper()

        result = self._make_request("/autocomplete", params)

        return self._pelias_validate_autocomplete(
            result,
            formatted_getter=lambda feature: feature.get("properties", {}).get("label", ""),
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
        """Geocode an address to coordinates using Geocode Earth autocomplete API."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_geocode_failure(msg),
        )
        if failure:
            return failure

        params: Dict[str, Any] = {"text": query_string, "size": 1}
        if country:
            params["boundary.country"] = country.upper()

        return self._pelias_geocode_request(
            endpoint="/autocomplete",
            params=params,
            formatted_getter=lambda feature: feature.get("properties", {}).get(
                "label", ""
            ),
        )

    def reverse_geocode(self, latitude: float, longitude: float, **kwargs: Any) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address using Geocode Earth."""
        params: Dict[str, Any] = {
            "point.lat": latitude,
            "point.lon": longitude,
        }
        if "language" in kwargs:
            params["lang"] = kwargs["language"]

        result = self._make_request("/reverse", params)

        if "error" in result:
            payload = self._build_empty_address_payload(error=result["error"])
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            payload["address_reference"] = None
            return payload

        features = result.get("features", [])
        return self._pelias_feature_payload(
            features,
            formatted_getter=lambda feature: feature.get("properties", {}).get("label", ""),
            missing_error="No address found",
            latitude=latitude,
            longitude=longitude,
        )

    def get_address_by_reference(self, address_reference: str, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve address details by a reference ID using Geocode Earth.

        Geocode Earth uses Pelias which supports lookup by GID (global ID).
        """
        params: Dict[str, Any] = {"ids": address_reference}
        result = self._make_request("/place", params)

        if "error" in result:
            return self._build_empty_address_payload(
                address_reference=address_reference, error=result["error"]
            )

        features = result.get("features", [])
        return self._pelias_feature_payload(
            features,
            formatted_getter=lambda feature: feature.get("properties", {}).get("label", ""),
            missing_error="Address not found for reference",
        )
