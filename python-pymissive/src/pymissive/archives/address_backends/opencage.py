"""OpenCage Geocoding API address verification backend."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAddressBackend


class OpenCageAddressBackend(BaseAddressBackend):
    """OpenCage Geocoding API backend for address verification.

    Free tier: 5000 requests/day.
    Requires API key (free registration).
    """

    name = "opencage"
    display_name = "OpenCage"
    config_keys = ["OPENCAGE_API_KEY", "OPENCAGE_BASE_URL"]
    required_packages = ["requests"]
    documentation_url = "https://opencagedata.com/api"
    site_url = "https://opencagedata.com"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize OpenCage backend.

        Args:
            config: Optional configuration dict with:
                - OPENCAGE_API_KEY: API key (required)
                - OPENCAGE_BASE_URL: Custom base URL (default: official)
        """
        super().__init__(config)
        self._api_key = self._config.get("OPENCAGE_API_KEY")
        if not self._api_key:
            raise ValueError("OPENCAGE_API_KEY is required")
        self._base_url = self._config.get(
            "OPENCAGE_BASE_URL", "https://api.opencagedata.com/geocode/v1"
        )
        self._last_request_time = 0.0

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the OpenCage API."""
        self._rate_limit_with_interval("_last_request_time", 0.5)

        default_params: Dict[str, Any] = {"key": self._api_key}
        return self._request_json(
            self._base_url,
            endpoint,
            params,
            default_params=default_params,
        )

    def _extract_address_from_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from an OpenCage result."""
        components = result.get("components", {})

        # Extract address_line1
        address_line1 = ""
        if components.get("house_number") and components.get("road"):
            address_line1 = f"{components.get('house_number')} {components.get('road')}".strip()
        elif components.get("road"):
            address_line1 = components.get("road", "")
        elif result.get("formatted"):
            # Fallback: use first part of formatted address
            formatted = result.get("formatted", "")
            parts = formatted.split(",")
            if parts:
                address_line1 = parts[0].strip()

        # Extract city (try multiple fields)
        city = (
            components.get("city")
            or components.get("town")
            or components.get("village")
            or components.get("municipality")
            or ""
        )

        # Extract state/region
        state = (
            components.get("state")
            or components.get("region")
            or components.get("state_district")
            or ""
        )

        # Extract country code
        country_code = (
            components.get("country_code", "").upper() if components.get("country_code") else ""
        )

        return {
            "address_line1": address_line1 or "",
            "address_line2": "",
            "address_line3": "",
            "city": city,
            "postal_code": components.get("postcode", ""),
            "state": state,
            "country": country_code,
            "address_reference": str(result.get("annotations", {}).get("geohash", "")),
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
        """Validate an address using OpenCage."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        params: Dict[str, Any] = {"q": query_string, "limit": 5, "no_annotations": 0}
        if country:
            params["countrycode"] = country.lower()
        if "language" in kwargs:
            params["language"] = kwargs["language"]

        result = self._make_request("/json", params)

        if "error" in result:
            return self._build_validation_failure(error=result["error"])

        results = result.get("results", [])

        def _extract_feature(feature: Dict[str, Any]) -> Dict[str, Any]:
            payload = self._extract_address_from_result(feature)
            geometry = feature.get("geometry", {})
            lat = geometry.get("lat")
            lon = geometry.get("lng")
            if lat is not None:
                payload["latitude"] = float(lat)
            if lon is not None:
                payload["longitude"] = float(lon)
            confidence_raw = feature.get("confidence", 0)
            payload["confidence"] = float(min(confidence_raw / 10.0, 1.0))
            annotations = feature.get("annotations", {})
            geohash = annotations.get("geohash")
            if geohash:
                payload["address_reference"] = str(geohash)
            return payload

        return self._feature_validation_payload(
            features=results,
            extractor=_extract_feature,
            formatted_getter=lambda feature: feature.get("formatted", ""),
            confidence_getter=lambda feature, normalized: normalized.get("confidence", 0.0),
            suggestion_formatter=lambda feature, normalized_suggestion: {
                "formatted_address": feature.get("formatted", ""),
                "confidence": normalized_suggestion.get("confidence", 0.0),
                "latitude": normalized_suggestion.get("latitude"),
                "longitude": normalized_suggestion.get("longitude"),
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
        """Geocode an address to coordinates using OpenCage."""

        def _request(query_string: str) -> Dict[str, Any]:
            params: Dict[str, Any] = {"q": query_string, "limit": 1, "no_annotations": 0}
            if country:
                params["countrycode"] = country.lower()
            if "language" in kwargs:
                params["language"] = kwargs["language"]
            return self._make_request("/json", params)

        accuracy_map = {
            "house_number": "ROOFTOP",
            "road": "STREET",
            "city": "CITY",
            "town": "CITY",
        }

        def _handle(result: Dict[str, Any], _query: str) -> Dict[str, Any]:
            results = result.get("results", [])

            def _extract_feature(feature: Dict[str, Any]) -> Dict[str, Any]:
                payload = self._extract_address_from_result(feature)
                geometry = feature.get("geometry", {})
                lat = geometry.get("lat")
                lon = geometry.get("lng")
                if lat is not None:
                    payload["latitude"] = float(lat)
                if lon is not None:
                    payload["longitude"] = float(lon)
                confidence_raw = feature.get("confidence", 0)
                payload["confidence"] = float(min(confidence_raw / 10.0, 1.0))
                annotations = feature.get("annotations", {})
                geohash = annotations.get("geohash")
                if geohash:
                    payload["address_reference"] = str(geohash)
                payload["formatted_address"] = feature.get("formatted", "")
                return payload

            def _accuracy_from_feature(
                feature: Dict[str, Any], _normalized: Dict[str, Any]
            ) -> str:
                components = feature.get("components", {})
                for key in ("house_number", "road", "city", "town"):
                    if components.get(key):
                        return accuracy_map[key]
                return "APPROXIMATE"

            return self._feature_geocode_payload(
                features=results,
                extractor=_extract_feature,
                formatted_getter=lambda feature: feature.get("formatted", ""),
                accuracy_getter=_accuracy_from_feature,
                confidence_getter=lambda feature, normalized: normalized.get("confidence", 0.0),
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
        """Reverse geocode coordinates to an address using OpenCage."""
        params: Dict[str, Any] = {
            "q": f"{latitude},{longitude}",
            "no_annotations": 0,
        }
        if "language" in kwargs:
            params["language"] = kwargs["language"]

        result = self._make_request("/json", params)

        if "error" in result:
            return self._build_empty_address_payload(error=result["error"])

        results = result.get("results", [])
        if not results:
            return self._build_empty_address_payload(error="No address found")

        best_match = results[0]
        normalized = self._extract_address_from_result(best_match)
        normalized["latitude"] = latitude
        normalized["longitude"] = longitude

        return {
            **normalized,
            "formatted_address": best_match.get("formatted", ""),
            "errors": [],
        }

    def get_address_by_reference(self, address_reference: str, **kwargs: Any) -> Dict[str, Any]:
        """Get address by reference ID using OpenCage.

        OpenCage uses geohash as reference.
        We can use reverse geocode with coordinates decoded from geohash.
        However, OpenCage doesn't have a direct lookup by geohash endpoint.
        """
        # OpenCage doesn't support direct lookup by geohash
        # We would need to decode geohash to coordinates and use reverse_geocode
        return self._build_empty_address_payload(
            error=(
                "OpenCage does not support direct lookup by reference ID. "
                "Use reverse_geocode with coordinates instead."
            )
        )
