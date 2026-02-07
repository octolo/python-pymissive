"""Mapbox address verification backend."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAddressBackend


class MapboxAddressBackend(BaseAddressBackend):
    """Mapbox Geocoding API backend for address verification.

    Requires the `requests` package and a Mapbox access token.
    """

    name = "mapbox"
    display_name = "Mapbox"
    config_keys = ["MAPBOX_ACCESS_TOKEN"]
    required_packages = ["requests"]
    documentation_url = "https://docs.mapbox.com/api/search/geocoding/"
    site_url = "https://www.mapbox.com"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Mapbox backend.

        Args:
            config: Configuration dict with MAPBOX_ACCESS_TOKEN.
        """
        super().__init__(config)
        self._access_token = self._config.get("MAPBOX_ACCESS_TOKEN")

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the Mapbox API."""
        if not self._access_token:
            return {"error": "MAPBOX_ACCESS_TOKEN not configured"}

        default_params = {"access_token": self._access_token}
        return self._request_json(
            "https://api.mapbox.com",
            endpoint,
            params,
            default_params=default_params,
        )

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
        """Validate an address using Mapbox Geocoding API."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        import urllib.parse

        # After checking failure is None, query_string is guaranteed to be str
        assert query_string is not None
        encoded_query = urllib.parse.quote(query_string)
        params: Dict[str, Any] = {"limit": 5}
        if country:
            params["country"] = country

        result = self._make_request(f"/geocoding/v5/mapbox.places/{encoded_query}.json", params)

        if "error" in result:
            return self._build_validation_failure(error=result["error"])

        features = result.get("features", [])

        def _extract_with_coordinates(feature: Dict[str, Any]) -> Dict[str, Any]:
            payload = self._extract_address_from_feature(feature)
            coords = feature.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                payload["longitude"] = float(coords[0])
                payload["latitude"] = float(coords[1])
            return payload

        return self._feature_validation_payload(
            features=features,
            extractor=_extract_with_coordinates,
            formatted_getter=lambda feature: feature.get("place_name", ""),
            confidence_getter=lambda feature, _normalized: float(
                feature.get("relevance", 0.0)
            ),
            suggestion_formatter=lambda feature, normalized_suggestion: {
                "formatted_address": feature.get("place_name", ""),
                "confidence": float(feature.get("relevance", 0.0)),
                "latitude": normalized_suggestion.get("latitude"),
                "longitude": normalized_suggestion.get("longitude"),
            },
            valid_threshold=0.7,
            warning_threshold=0.9,
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
        """Geocode an address to coordinates using Mapbox."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_geocode_failure(msg),
        )
        if failure:
            return failure

        import urllib.parse

        # After checking failure is None, query_string is guaranteed to be str
        assert query_string is not None
        encoded_query = urllib.parse.quote(query_string)
        params: Dict[str, Any] = {"limit": 1}
        if country:
            params["country"] = country

        result = self._make_request(f"/geocoding/v5/mapbox.places/{encoded_query}.json", params)

        if "error" in result:
            return self._build_geocode_failure(error=result["error"])

        features = result.get("features", [])
        accuracy_map = {
            "address": "ROOFTOP",
            "poi": "ROOFTOP",
            "neighborhood": "STREET",
            "locality": "CITY",
            "place": "CITY",
            "district": "CITY",
            "region": "REGION",
            "country": "COUNTRY",
        }

        def _extract_with_coordinates(feature: Dict[str, Any]) -> Dict[str, Any]:
            payload = self._extract_address_from_feature(feature)
            coords = feature.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                payload["latitude"] = float(coords[1])
                payload["longitude"] = float(coords[0])
            return payload

        return self._feature_geocode_payload(
            features=features,
            extractor=_extract_with_coordinates,
            formatted_getter=lambda feature: feature.get("place_name", ""),
            accuracy_getter=lambda feature, _normalized: accuracy_map.get(
                feature.get("properties", {}).get("type", ""), "UNKNOWN"
            ),
            confidence_getter=lambda feature, _normalized: float(
                feature.get("relevance", 0.0)
            ),
            missing_error="No address found",
        )

    def reverse_geocode(self, latitude: float, longitude: float, **kwargs: Any) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address using Mapbox."""
        params: Dict[str, Any] = {"limit": 1}
        if "language" in kwargs:
            params["language"] = kwargs["language"]

        result = self._make_request(
            f"/geocoding/v5/mapbox.places/{longitude},{latitude}.json", params
        )

        if "error" in result:
            return self._build_empty_address_payload(error=result["error"])

        features = result.get("features", [])
        if not features:
            return self._build_empty_address_payload(error="No address found")

        feature = features[0]
        normalized = self._extract_address_from_feature(feature)
        feature_id = feature.get("id")

        return {
            **normalized,
            "formatted_address": feature.get("place_name", ""),
            "confidence": feature.get("relevance", 0.0),
            "address_reference": (
                str(feature_id) if feature_id is not None else normalized.get("address_reference")
            ),
            "errors": [],
        }

    def get_address_by_reference(self, address_reference: str, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve an address by its feature ID using Mapbox Geocoding API."""
        if not address_reference:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="address_reference is required",
            )

        import urllib.parse

        encoded_id = urllib.parse.quote(address_reference)
        params: Dict[str, Any] = {}
        if "language" in kwargs:
            params["language"] = kwargs["language"]

        result = self._make_request(f"/geocoding/v5/mapbox.places/{encoded_id}.json", params)

        if "error" in result:
            return self._build_empty_address_payload(
                address_reference=address_reference, error=result["error"]
            )

        features = result.get("features", [])
        if not features:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="No address found for this feature ID",
            )

        feature = features[0]
        normalized = self._extract_address_from_feature(feature)

        coordinates = feature.get("geometry", {}).get("coordinates", [])

        return {
            **normalized,
            "formatted_address": feature.get("place_name", ""),
            "latitude": coordinates[1] if len(coordinates) >= 2 else None,
            "longitude": coordinates[0] if len(coordinates) >= 1 else None,
            "confidence": feature.get("relevance", 0.0),
            "address_reference": address_reference,
            "errors": [],
        }

    def _extract_address_from_feature(self, feature: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from a Mapbox feature."""
        properties = feature.get("properties", {})
        context = feature.get("context", [])

        # Extract address_line1 - try multiple sources
        address_line1 = properties.get("address", "")

        # If address is empty, try to extract from place_name (first part before comma)
        if not address_line1:
            place_name = feature.get("place_name", "")
            if place_name:
                # Extract the first part (before first comma) which usually contains number + street
                parts = place_name.split(",")
                if parts:
                    address_line1 = parts[0].strip()

        # If still empty, try to build from address_number + street
        if not address_line1:
            address_number = properties.get("address_number", "")
            street = properties.get("street", "")
            if address_number and street:
                address_line1 = f"{address_number} {street}".strip()
            elif street:
                address_line1 = street

        # If still empty, try text property (usually contains the street name)
        if not address_line1:
            text = feature.get("text", "")
            if text:
                address_line1 = text

        city = None
        postal_code = None
        state = None
        country = None

        for item in context:
            item_id = item.get("id", "")
            if item_id.startswith("postcode"):
                postal_code = item.get("text", "")
            elif item_id.startswith("place"):
                city = item.get("text", "")
            elif item_id.startswith("region"):
                state = item.get("text", "")
            elif item_id.startswith("country"):
                country = item.get("short_code", "").upper()

        # Extract feature id for reverse lookup
        feature_id = feature.get("id")

        return {
            "address_line1": address_line1 or "",
            "address_line2": "",
            "address_line3": "",
            "city": city or "",
            "postal_code": postal_code or "",
            "state": state or "",
            "country": country or "",
            "address_reference": str(feature_id) if feature_id is not None else None,
        }
