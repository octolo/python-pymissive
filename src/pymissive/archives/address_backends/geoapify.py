"""Geoapify API address verification backend."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAddressBackend
from .pelias_mixin import PeliasFeatureMixin


class GeoapifyAddressBackend(PeliasFeatureMixin, BaseAddressBackend):
    """Geoapify Geocoding API backend for address verification.

    Geoapify provides geocoding, reverse geocoding, and autocomplete services.
    Free tier: 3000 requests/day.
    Requires API key (free registration).
    """

    name = "geoapify"
    display_name = "Geoapify"
    config_keys = ["GEOAPIFY_API_KEY", "GEOAPIFY_BASE_URL"]
    required_packages = ["requests"]
    documentation_url = "https://apidocs.geoapify.com/docs/geocoding/"
    site_url = "https://www.geoapify.com"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Geoapify backend.

        Args:
            config: Optional configuration dict with:
                - GEOAPIFY_API_KEY: API key (required)
                - GEOAPIFY_BASE_URL: Custom base URL (default: official)
        """
        super().__init__(config)
        self._api_key = self._config.get("GEOAPIFY_API_KEY")
        if not self._api_key:
            raise ValueError("GEOAPIFY_API_KEY is required")
        self._base_url = self._config.get("GEOAPIFY_BASE_URL", "https://api.geoapify.com/v1")
        self._last_request_time = 0.0

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the Geoapify API."""
        self._rate_limit_with_interval("_last_request_time", 0.1)

        default_params = {"apiKey": self._api_key}
        return self._request_json(
            self._base_url,
            endpoint,
            params,
            default_params=default_params,
        )

    def _extract_address_from_feature(self, feature: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from a Geoapify feature."""
        properties = feature.get("properties", {})

        # Geoapify provides address_line1 directly, or build from housenumber and street
        address_line1 = properties.get("address_line1", "")
        if not address_line1:
            address_line1_parts = []
            if properties.get("housenumber"):
                address_line1_parts.append(str(properties["housenumber"]))
            if properties.get("street"):
                address_line1_parts.append(properties["street"])
            address_line1 = " ".join(address_line1_parts).strip()

        # Extract coordinates - Geoapify provides lat/lon directly in properties
        latitude = None
        longitude = None
        if "lat" in properties and properties["lat"] is not None:
            latitude = float(properties["lat"])
        if "lon" in properties and properties["lon"] is not None:
            longitude = float(properties["lon"])

        # Fallback to geometry if not in properties (GeoJSON format: [longitude, latitude])
        if latitude is None or longitude is None:
            geometry = feature.get("geometry", {})
            coordinates = geometry.get("coordinates", [])
            if len(coordinates) >= 2:
                if longitude is None:
                    longitude = float(coordinates[0])
                if latitude is None:
                    latitude = float(coordinates[1])

        # Extract confidence - Geoapify provides it as 0-1 scale in rank.confidence
        confidence = 0.0
        rank = properties.get("rank", {})
        if rank and "confidence" in rank:
            confidence = float(rank["confidence"])

        return {
            "address_line1": address_line1 or "",
            "address_line2": properties.get("district", "") or properties.get("suburb", ""),
            "address_line3": properties.get("neighbourhood", ""),
            "city": properties.get("city", "")
            or properties.get("town", "")
            or properties.get("village", "")
            or properties.get("municipality", ""),
            "postal_code": properties.get("postcode", ""),
            "state": properties.get("state", "") or properties.get("state_code", ""),
            "country": (
                properties.get("country_code", "").upper() if properties.get("country_code") else ""
            ),
            "address_reference": properties.get("place_id") or feature.get("id"),
            "latitude": latitude,
            "longitude": longitude,
            "confidence": confidence,
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
        """Validate an address using Geoapify autocomplete API."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        params: Dict[str, Any] = {"text": query_string, "limit": 5}
        if country:
            params["filter"] = f"countrycode:{country.upper()}"

        result = self._make_request("/geocode/autocomplete", params)

        return self._pelias_validate_autocomplete(
            result,
            formatted_getter=lambda feature: feature.get("properties", {}).get(
                "formatted", ""
            ),
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
        """Geocode an address to coordinates using Geoapify."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_geocode_failure(msg),
        )
        if failure:
            return failure

        params: Dict[str, Any] = {"text": query_string, "limit": 1}
        if country:
            params["filter"] = f"countrycode:{country.upper()}"

        return self._pelias_geocode_request(
            endpoint="/geocode/search",
            params=params,
            formatted_getter=lambda feature: feature.get("properties", {}).get(
                "formatted", ""
            ),
        )

    def reverse_geocode(self, latitude: float, longitude: float, **kwargs: Any) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address using Geoapify."""
        params: Dict[str, Any] = {"lat": latitude, "lon": longitude}
        if "language" in kwargs:
            params["lang"] = kwargs["language"]

        result = self._make_request("/geocode/reverse", params)

        if "error" in result:
            payload = self._build_empty_address_payload(error=result["error"])
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            payload["address_reference"] = None
            return payload

        features = result.get("features", [])
        return self._pelias_feature_payload(
            features,
            formatted_getter=lambda feature: feature.get("properties", {}).get("formatted", ""),
            missing_error="No address found",
            latitude=latitude,
            longitude=longitude,
        )

    def get_address_by_reference(self, address_reference: str, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve address details by a reference ID using Geoapify.

        Geoapify supports lookup by place_id.
        """
        params: Dict[str, Any] = {"place_id": address_reference}
        result = self._make_request("/geocode/search", params)

        if "error" in result:
            return self._build_empty_address_payload(
                address_reference=address_reference, error=result["error"]
            )

        features = result.get("features", [])
        return self._pelias_feature_payload(
            features,
            formatted_getter=lambda feature: feature.get("properties", {}).get("formatted", ""),
            missing_error="Address not found for reference",
        )
