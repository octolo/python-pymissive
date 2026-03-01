"""LocationIQ address verification backend."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

from .base import BaseAddressBackend


class LocationIQAddressBackend(BaseAddressBackend):
    """LocationIQ Geocoding API backend for address verification.

    Free tier: 5000 requests/day.
    Requires API key (free registration).
    """

    name = "locationiq"
    display_name = "LocationIQ"
    config_keys = ["LOCATIONIQ_API_KEY", "LOCATIONIQ_BASE_URL"]
    required_packages = ["requests"]
    documentation_url = "https://docs.locationiq.com/"
    site_url = "https://locationiq.com"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize LocationIQ backend.

        Args:
            config: Optional configuration dict with:
                - LOCATIONIQ_API_KEY: API key (required)
                - LOCATIONIQ_BASE_URL: Custom base URL (default: official)
        """
        super().__init__(config)
        self._api_key = self._config.get("LOCATIONIQ_API_KEY")
        if not self._api_key:
            raise ValueError("LOCATIONIQ_API_KEY is required")
        self._base_url = self._config.get("LOCATIONIQ_BASE_URL", "https://api.locationiq.com/v1")
        self._last_request_time = 0.0

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the LocationIQ API."""
        try:
            import requests
        except ImportError:
            return {"error": "requests package not installed"}

        self._rate_limit_with_interval("_last_request_time", 0.5)

        url = f"{self._base_url}{endpoint}"

        request_params: Dict[str, Any] = {
            "key": self._api_key,
            "format": "json",
        }
        if params:
            request_params.update(params)

        try:
            response = requests.get(url, params=request_params, timeout=10)
            response.raise_for_status()
            return cast(Dict[str, Any], response.json())
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def _extract_address_from_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from a LocationIQ result."""
        address = result.get("address", {})

        # Extract address_line1
        address_line1 = ""
        if address.get("house_number") and address.get("road"):
            address_line1 = f"{address.get('house_number')} {address.get('road')}".strip()
        elif address.get("road"):
            address_line1 = address.get("road", "")
        elif result.get("display_name"):
            # Fallback: use first part of display_name
            display_name = result.get("display_name", "")
            parts = display_name.split(",")
            if parts:
                address_line1 = parts[0].strip()

        return {
            "address_line1": address_line1 or "",
            "address_line2": "",
            "address_line3": "",
            "city": address.get("city") or address.get("town") or address.get("village") or "",
            "postal_code": address.get("postcode", ""),
            "state": address.get("state") or address.get("region", ""),
            "country": (
                address.get("country_code", "").upper() if address.get("country_code") else ""
            ),
            "address_reference": str(result.get("place_id", "")),
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
        """Validate an address using LocationIQ."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        params: Dict[str, Any] = {"q": query_string, "limit": 5, "addressdetails": 1}
        if country:
            params["countrycodes"] = country.lower()

        result = self._make_request("/search.php", params)

        if "error" in result:
            return self._build_validation_failure(error=result["error"])

        results: List[Dict[str, Any]]
        if isinstance(result, list):
            results = result
        else:
            results = [result] if result else []

        def _extract_with_coordinates(feature: Dict[str, Any]) -> Dict[str, Any]:
            payload = self._extract_address_from_result(feature)
            lat = feature.get("lat")
            lon = feature.get("lon")
            if lat is not None and lon is not None:
                payload["latitude"] = float(lat)
                payload["longitude"] = float(lon)
            return payload

        payload = self._feature_validation_payload(
            features=results,
            extractor=_extract_with_coordinates,
            formatted_getter=lambda feature: feature.get("display_name", ""),
            confidence_getter=lambda feature, _normalized: float(
                min(feature.get("importance", 0.0), 1.0)
            ),
            suggestion_formatter=lambda feature, normalized_suggestion: {
                "formatted_address": feature.get("display_name", ""),
                "confidence": float(min(feature.get("importance", 0.0), 1.0)),
                "latitude": normalized_suggestion.get("latitude"),
                "longitude": normalized_suggestion.get("longitude"),
            },
            valid_threshold=0.5,
            warning_threshold=0.7,
            missing_error="No address found",
            max_suggestions=4,
        )

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
        """Geocode an address to coordinates using LocationIQ."""

        def _request(query_string: str) -> Dict[str, Any]:
            params: Dict[str, Any] = {"q": query_string, "limit": 1, "addressdetails": 1}
            if country:
                params["countrycodes"] = country.lower()
            return self._make_request("/search.php", params)

        accuracy_map = {
            "house": "ROOFTOP",
            "building": "ROOFTOP",
            "address": "ROOFTOP",
            "street": "STREET",
            "city": "CITY",
            "town": "CITY",
            "village": "CITY",
        }

        def _handle(result: Dict[str, Any], _query: str) -> Dict[str, Any]:
            if isinstance(result, list):
                results = result
            else:
                results = [result] if result else []

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
                features=results,
                extractor=_extract_with_coordinates,
                formatted_getter=lambda feature: feature.get("display_name", ""),
                accuracy_getter=lambda feature, _normalized: accuracy_map.get(
                    feature.get("type", ""), "APPROXIMATE"
                ),
                confidence_getter=lambda feature, _normalized: float(
                    min(feature.get("importance", 0.0), 1.0)
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

    def reverse_geocode(self, latitude: float, longitude: float, **kwargs: Any) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address using LocationIQ."""
        params: Dict[str, Any] = {
            "lat": str(latitude),
            "lon": str(longitude),
            "addressdetails": 1,
        }
        if "language" in kwargs:
            params["accept-language"] = kwargs["language"]

        result = self._make_request("/reverse.php", params)

        if "error" in result:
            return self._build_empty_address_payload(error=result["error"])

        normalized = self._extract_address_from_result(result)
        normalized["latitude"] = latitude
        normalized["longitude"] = longitude

        return {
            **normalized,
            "formatted_address": result.get("display_name", ""),
            "errors": [],
        }

    def get_address_by_reference(self, address_reference: str, **kwargs: Any) -> Dict[str, Any]:
        """Get address by reference ID using LocationIQ.

        LocationIQ uses place_id for reverse lookup.
        We can use the reverse geocode with coordinates if available,
        or search with place_id.

        Note: LocationIQ doesn't have a direct lookup by place_id endpoint,
        so we'll need to use coordinates if they're stored with the reference.
        """
        # LocationIQ place_id format is numeric
        # Without a direct lookup endpoint, we return an error
        return self._build_empty_address_payload(
            error=(
                "LocationIQ does not support direct lookup by reference ID. "
                "Use reverse_geocode with coordinates instead."
            )
        )
