"""Nominatim (OpenStreetMap) address verification backend."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAddressBackend


class NominatimAddressBackend(BaseAddressBackend):
    """Nominatim (OpenStreetMap) Geocoding API backend for address verification.

    Completely free, no API key required. Uses OpenStreetMap data.
    Rate limit: 1 request per second (respected automatically).
    """

    name = "nominatim"
    display_name = "OpenStreetMap Nominatim"
    config_keys = ["NOMINATIM_BASE_URL", "NOMINATIM_USER_AGENT"]
    required_packages = ["requests"]
    documentation_url = "https://nominatim.org/release-docs/develop/api/Overview/"
    site_url = "https://nominatim.org"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Nominatim backend.

        Args:
            config: Optional configuration dict with:
                - NOMINATIM_BASE_URL: Custom Nominatim server URL (default: official)
                - NOMINATIM_USER_AGENT: User agent string (required by ToS)
        """
        super().__init__(config)
        self._base_url = self._config.get(
            "NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"
        )
        self._user_agent = self._config.get(
            "NOMINATIM_USER_AGENT", "python-missive/1.0"
        )
        self._last_request_time = 0.0

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the Nominatim API."""
        self._rate_limit_with_interval("_last_request_time", 1.0)

        default_params: Dict[str, Any] = {
            "format": "json",
            "addressdetails": 1,
            "limit": 5,
        }
        headers = {"User-Agent": self._user_agent}

        return self._request_json(
            self._base_url,
            endpoint,
            params,
            default_params=default_params,
            headers=headers,
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
        """Validate an address using Nominatim."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        params = {"q": query_string}
        if country:
            params["countrycodes"] = country.lower()

        result = self._make_request("/search", params)

        if "error" in result:
            return self._build_validation_failure(error=result["error"])

        features: list[Dict[str, Any]] = result if isinstance(result, list) else []

        def _extract_with_coordinates(feature: Dict[str, Any]) -> Dict[str, Any]:
            payload = self._extract_address_from_result(feature)
            lat = feature.get("lat")
            lon = feature.get("lon")
            if lat and lon:
                payload["latitude"] = float(lat)
                payload["longitude"] = float(lon)
            return payload

        payload = self._feature_validation_payload(
            features=features,
            extractor=_extract_with_coordinates,
            formatted_getter=lambda feature: feature.get("display_name", ""),
            confidence_getter=lambda feature, _normalized: float(
                min(feature.get("importance", 0.0) * 2.0, 1.0)
            ),
            suggestion_formatter=lambda feature, normalized_suggestion: {
                "formatted_address": feature.get("display_name", ""),
                "confidence": float(
                    min(feature.get("importance", 0.0) * 2.0, 1.0)
                ),
                "latitude": normalized_suggestion.get("latitude"),
                "longitude": normalized_suggestion.get("longitude"),
            },
            valid_threshold=0.5,
            warning_threshold=0.7,
            missing_error="No address found",
            max_suggestions=4,
        )

        if features:
            importance = features[0].get("importance", 0.0)
            if importance < 0.5:
                payload["warnings"].append("Low importance match")

        return payload

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
        """Geocode an address to coordinates using Nominatim."""

        def _request(query_string: str) -> Dict[str, Any]:
            params = {"q": query_string, "limit": 1}
            if country:
                params["countrycodes"] = country.lower()
            return self._make_request("/search", params)

        accuracy_map = {
            "house": "ROOFTOP",
            "building": "ROOFTOP",
            "place": "STREET",
            "highway": "STREET",
            "amenity": "STREET",
            "boundary": "CITY",
            "administrative": "CITY",
        }

        def _handle(result: Dict[str, Any], _query: str) -> Dict[str, Any]:
            features: list[Dict[str, Any]] = result if isinstance(result, list) else []

            def _extract_with_coordinates(feature: Dict[str, Any]) -> Dict[str, Any]:
                payload = self._extract_address_from_result(feature)
                lat = feature.get("lat")
                lon = feature.get("lon")
                if lat is not None:
                    payload["latitude"] = float(lat)
                if lon is not None:
                    payload["longitude"] = float(lon)
                return payload

            return self._feature_geocode_payload(
                features=features,
                extractor=_extract_with_coordinates,
                formatted_getter=lambda feature: feature.get("display_name", ""),
                accuracy_getter=lambda feature, _normalized: accuracy_map.get(
                    feature.get("class", ""), "UNKNOWN"
                ),
                confidence_getter=lambda feature, _normalized: float(
                    min(feature.get("importance", 0.0) * 2.0, 1.0)
                ),
                missing_error="No address found",
            )

        return self._execute_geocode_flow(
            query=query,
            context=locals(),
            failure_builder=self._build_geocode_failure,
            request_callable=_request,
            result_handler=_handle,
        )

    def reverse_geocode(
        self, latitude: float, longitude: float, **kwargs: Any
    ) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address using Nominatim."""
        params = {"lat": str(latitude), "lon": str(longitude)}
        if "language" in kwargs:
            params["accept-language"] = kwargs["language"]

        result = self._make_request("/reverse", params)

        if "error" in result:
            return {
                "address_line1": None,
                "address_line2": None,
                "address_line3": None,
                "city": None,
                "postal_code": None,
                "state": None,
                "country": None,
                "formatted_address": None,
                "confidence": 0.0,
                "errors": [result["error"]],
            }

        if not isinstance(result, dict):
            return {
                "address_line1": None,
                "address_line2": None,
                "address_line3": None,
                "city": None,
                "postal_code": None,
                "state": None,
                "country": None,
                "formatted_address": None,
                "confidence": 0.0,
                "errors": ["No address found"],
            }

        normalized = self._extract_address_from_result(result)

        lat = result.get("lat")
        lon = result.get("lon")
        if lat and lon:
            normalized["latitude"] = float(lat)
            normalized["longitude"] = float(lon)

        importance = result.get("importance", 0.0)
        confidence = min(importance * 2.0, 1.0)
        place_id = result.get("place_id")

        return {
            **normalized,
            "formatted_address": result.get("display_name", ""),
            "confidence": confidence,
            "address_reference": (
                str(place_id) if place_id else normalized.get("address_reference")
            ),
            "errors": [],
        }

    def get_address_by_reference(
        self, address_reference: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """Retrieve an address by its place_id using Nominatim lookup endpoint."""
        if not address_reference:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="address_reference is required",
            )

        try:
            place_id = int(address_reference)
        except (ValueError, TypeError):
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="Invalid place_id format",
            )

        params = {"place_id": place_id, "format": "json", "addressdetails": 1}
        if "language" in kwargs:
            params["accept-language"] = kwargs["language"]

        result = self._make_request("/lookup", params)

        if "error" in result:
            return self._build_empty_address_payload(
                address_reference=address_reference, error=result["error"]
            )

        if not isinstance(result, list) or not result:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="No address found for this place_id",
            )

        address_result = result[0]
        normalized = self._extract_address_from_result(address_result)

        lat = address_result.get("lat")
        lon = address_result.get("lon")
        importance = address_result.get("importance", 0.0)
        confidence = min(importance * 2.0, 1.0)

        return {
            **normalized,
            "formatted_address": address_result.get("display_name", ""),
            "latitude": float(lat) if lat else None,
            "longitude": float(lon) if lon else None,
            "confidence": confidence,
            "address_reference": address_reference,
            "errors": [],
        }

    def _extract_address_from_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from a Nominatim result."""
        address = result.get("address", {})

        address_line1 = ""
        house_number = address.get("house_number", "")
        road = address.get("road", "")
        if house_number and road:
            address_line1 = f"{house_number} {road}".strip()
        elif road:
            address_line1 = road

        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or ""
        )
        postal_code = address.get("postcode", "")
        state = (
            address.get("state")
            or address.get("region")
            or address.get("province")
            or ""
        )
        country = address.get("country_code", "").upper()

        # Extract place_id for reverse lookup
        place_id = result.get("place_id")

        return {
            "address_line1": address_line1,
            "address_line2": "",
            "address_line3": "",
            "city": city,
            "postal_code": postal_code,
            "state": state,
            "country": country,
            "address_reference": str(place_id) if place_id else None,
        }
