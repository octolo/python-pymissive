"""Google Maps address verification backend."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAddressBackend


class GoogleMapsAddressBackend(BaseAddressBackend):
    """Google Maps Geocoding API backend for address verification.

    Requires the `requests` package and a Google Maps API key.
    """

    name = "google_maps"
    display_name = "Google Maps"
    config_keys = ["GOOGLE_MAPS_API_KEY"]
    required_packages = ["requests"]
    documentation_url = "https://developers.google.com/maps/documentation/geocoding"
    site_url = "https://developers.google.com/maps"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Google Maps backend.

        Args:
            config: Configuration dict with GOOGLE_MAPS_API_KEY.
        """
        super().__init__(config)
        self._api_key = self._config.get("GOOGLE_MAPS_API_KEY")

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the Google Maps API."""
        if not self._api_key:
            return {"error": "GOOGLE_MAPS_API_KEY not configured"}

        default_params: Dict[str, Any] = {"key": self._api_key}
        return self._request_json(
            "https://maps.googleapis.com/maps/api",
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
        """Validate an address using Google Maps Geocoding API."""
        address, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        params = {"address": address}
        if country:
            params["region"] = country.lower()

        result = self._make_request("/geocode/json", params)

        if "error" in result:
            return self._build_validation_failure(error=result["error"])

        if result.get("status") != "OK":
            error_msg = result.get(
                "error_message", result.get("status", "Unknown error")
            )
            return self._build_validation_failure(error=error_msg)

        results = result.get("results", [])
        if not results:
            return self._build_validation_failure(error="No address found")

        best_match = results[0]
        normalized = self._extract_address_from_result(best_match)

        location_type = best_match.get("geometry", {}).get("location_type", "")
        confidence_map = {
            "ROOFTOP": 1.0,
            "RANGE_INTERPOLATED": 0.9,
            "GEOMETRIC_CENTER": 0.7,
            "APPROXIMATE": 0.5,
        }
        confidence = confidence_map.get(location_type, 0.5)
        is_valid = confidence >= 0.7

        suggestions = []
        if not is_valid and len(results) > 1:
            for result_item in results[1:5]:
                suggestions.append(
                    {
                        "formatted_address": result_item.get("formatted_address", ""),
                        "confidence": confidence_map.get(
                            result_item.get("geometry", {}).get("location_type", ""),
                            0.5,
                        ),
                    }
                )

        warnings = []
        if location_type == "APPROXIMATE":
            warnings.append("Address is approximate, not exact")
        if confidence < 0.9:
            warnings.append("Low confidence match")

        place_id = best_match.get("place_id")

        return {
            "is_valid": is_valid,
            "normalized_address": normalized,
            "confidence": confidence,
            "suggestions": suggestions,
            "warnings": warnings,
            "errors": [],
            "address_reference": (
                place_id if place_id else normalized.get("address_reference")
            ),
        }

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
        """Geocode an address to coordinates using Google Maps."""
        address, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_geocode_failure(msg),
        )
        if failure:
            return failure

        params = {"address": address}
        if country:
            params["region"] = country.lower()

        result = self._make_request("/geocode/json", params)

        if "error" in result:
            return self._build_geocode_failure(error=result["error"])

        if result.get("status") != "OK":
            error_msg = result.get(
                "error_message", result.get("status", "Unknown error")
            )
            return self._build_geocode_failure(error=error_msg)

        results = result.get("results", [])
        if not results:
            return self._build_geocode_failure(error="No address found")

        best_result = results[0]
        geometry = best_result.get("geometry", {})
        location = geometry.get("location", {})
        location_type = geometry.get("location_type", "")

        accuracy_map = {
            "ROOFTOP": "ROOFTOP",
            "RANGE_INTERPOLATED": "STREET",
            "GEOMETRIC_CENTER": "CITY",
            "APPROXIMATE": "CITY",
        }
        accuracy = accuracy_map.get(location_type, "UNKNOWN")

        confidence_map = {
            "ROOFTOP": 1.0,
            "RANGE_INTERPOLATED": 0.9,
            "GEOMETRIC_CENTER": 0.7,
            "APPROXIMATE": 0.5,
        }
        confidence = confidence_map.get(location_type, 0.5)
        place_id = best_result.get("place_id")

        return {
            "latitude": location.get("lat"),
            "longitude": location.get("lng"),
            "accuracy": accuracy,
            "confidence": confidence,
            "formatted_address": best_result.get("formatted_address", ""),
            "address_reference": place_id if place_id else None,
            "errors": [],
        }

    def reverse_geocode(
        self, latitude: float, longitude: float, **kwargs: Any
    ) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address using Google Maps."""
        params = {"latlng": f"{latitude},{longitude}"}
        if "language" in kwargs:
            params["language"] = kwargs["language"]

        result = self._make_request("/geocode/json", params)

        if "error" in result:
            payload = self._build_empty_address_payload(error=result["error"])
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            return payload

        if result.get("status") != "OK":
            error_msg = result.get(
                "error_message", result.get("status", "Unknown error")
            )
            payload = self._build_empty_address_payload(error=error_msg)
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            return payload

        results = result.get("results", [])
        if not results:
            payload = self._build_empty_address_payload(error="No address found")
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            return payload

        best_result = results[0]
        normalized = self._extract_address_from_result(best_result)

        location_type = best_result.get("geometry", {}).get("location_type", "")
        confidence_map = {
            "ROOFTOP": 1.0,
            "RANGE_INTERPOLATED": 0.9,
            "GEOMETRIC_CENTER": 0.7,
            "APPROXIMATE": 0.5,
        }
        confidence = confidence_map.get(location_type, 0.5)
        place_id = best_result.get("place_id")

        return {
            **normalized,
            "formatted_address": best_result.get("formatted_address", ""),
            "confidence": confidence,
            "address_reference": (
                place_id if place_id else normalized.get("address_reference")
            ),
            "errors": [],
        }

    def get_address_by_reference(
        self, address_reference: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """Retrieve an address by its place_id using Google Maps Places API."""
        if not address_reference:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="address_reference is required",
            )

        params = {"place_id": address_reference}
        if "language" in kwargs:
            params["language"] = kwargs["language"]

        result = self._make_request("/geocode/json", params)

        if "error" in result:
            return self._build_empty_address_payload(
                address_reference=address_reference, error=result["error"]
            )

        if result.get("status") != "OK":
            error_msg = result.get(
                "error_message", result.get("status", "Unknown error")
            )
            return self._build_empty_address_payload(
                address_reference=address_reference, error=error_msg
            )

        results = result.get("results", [])
        if not results:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="No address found for this place_id",
            )

        best_result = results[0]
        normalized = self._extract_address_from_result(best_result)

        geometry = best_result.get("geometry", {})
        location = geometry.get("location", {})
        location_type = geometry.get("location_type", "")

        confidence_map = {
            "ROOFTOP": 1.0,
            "RANGE_INTERPOLATED": 0.9,
            "GEOMETRIC_CENTER": 0.7,
            "APPROXIMATE": 0.5,
        }
        confidence = confidence_map.get(location_type, 0.5)

        return {
            **normalized,
            "formatted_address": best_result.get("formatted_address", ""),
            "latitude": location.get("lat"),
            "longitude": location.get("lng"),
            "confidence": confidence,
            "address_reference": address_reference,
            "errors": [],
        }

    def _extract_address_from_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from a Google Maps result."""
        address_components = result.get("address_components", [])

        address_line1 = ""
        address_line2 = ""
        city = ""
        postal_code = ""
        state = ""
        country = ""

        street_number = ""
        route = ""

        for component in address_components:
            types = component.get("types", [])
            long_name = component.get("long_name", "")
            short_name = component.get("short_name", "")

            if "street_number" in types:
                street_number = long_name
            elif "route" in types:
                route = long_name
            elif "postal_code" in types:
                postal_code = long_name
            elif "locality" in types or "sublocality" in types:
                if not city:
                    city = long_name
            elif "administrative_area_level_1" in types:
                state = long_name
            elif "country" in types:
                country = short_name.upper()

        if street_number and route:
            address_line1 = f"{street_number} {route}".strip()
        elif route:
            address_line1 = route

        # Extract place_id for reverse lookup
        place_id = result.get("place_id")

        return {
            "address_line1": address_line1,
            "address_line2": address_line2,
            "address_line3": "",
            "city": city,
            "postal_code": postal_code,
            "state": state,
            "country": country,
            "address_reference": place_id if place_id else None,
        }
