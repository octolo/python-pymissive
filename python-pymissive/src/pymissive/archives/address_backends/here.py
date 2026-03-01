"""HERE address verification backend."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAddressBackend


class HereAddressBackend(BaseAddressBackend):
    """HERE Geocoding API backend for address verification.

    Requires the `requests` package and HERE API credentials (app_id and app_code).
    """

    name = "here"
    display_name = "HERE"
    config_keys = ["HERE_APP_ID", "HERE_APP_CODE"]
    required_packages = ["requests"]
    documentation_url = "https://developer.here.com/documentation/geocoding-search-api"
    site_url = "https://developer.here.com"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize HERE backend.

        Args:
            config: Configuration dict with HERE_APP_ID and HERE_APP_CODE.
        """
        super().__init__(config)
        self._app_id = self._config.get("HERE_APP_ID")
        self._app_code = self._config.get("HERE_APP_CODE")

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the HERE API."""
        if not self._app_id or not self._app_code:
            return {"error": "HERE_APP_ID and HERE_APP_CODE must be configured"}

        default_params: Dict[str, Any] = {
            "app_id": self._app_id,
            "app_code": self._app_code,
        }

        return self._request_json(
            "https://geocoder.api.here.com/6.2",
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
        """Validate an address using HERE Geocoding API."""
        search_text, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        params = {"searchtext": search_text, "maxresults": 5}
        if country:
            params["country"] = country

        result = self._make_request("/geocode.json", params)

        if "error" in result:
            return self._build_validation_failure(error=result["error"])

        response = result.get("Response", {})
        view = response.get("View", [])
        results = view[0].get("Result", []) if view else []

        def _extract_feature(result_item: Dict[str, Any]) -> Dict[str, Any]:
            payload = self._extract_address_from_result(result_item)
            display_position = (
                result_item.get("Location", {}).get("DisplayPosition", {}) or {}
            )
            lat = display_position.get("Latitude")
            lon = display_position.get("Longitude")
            if lat is not None and lon is not None:
                payload["latitude"] = float(lat)
                payload["longitude"] = float(lon)
            return payload

        payload = self._feature_validation_payload(
            features=results,
            extractor=_extract_feature,
            formatted_getter=lambda item: item.get("Location", {})
            .get("Address", {})
            .get("Label", ""),
            confidence_getter=lambda item, _normalized: float(
                (item.get("MatchQuality", {}).get("Relevance", 0.0) or 0.0) / 100.0
            ),
            suggestion_formatter=lambda item, normalized_suggestion: {
                "formatted_address": item.get("Location", {})
                .get("Address", {})
                .get("Label", ""),
                "confidence": float(
                    (item.get("MatchQuality", {}).get("Relevance", 0.0) or 0.0) / 100.0
                ),
                "latitude": normalized_suggestion.get("latitude"),
                "longitude": normalized_suggestion.get("longitude"),
            },
            valid_threshold=0.7,
            warning_threshold=0.9,
            missing_error="No address found",
            max_suggestions=4,
        )

        if results:
            match_level = (
                results[0].get("MatchQuality", {}).get("MatchLevel", "") or ""
            )
            if match_level not in ("houseNumber", "street"):
                payload["warnings"].append(
                    f"Match level is {match_level}, not exact address"
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
        """Geocode an address to coordinates using HERE."""
        search_text, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_geocode_failure(msg),
        )
        if failure:
            return failure

        params = {"searchtext": search_text, "maxresults": 1}
        if country:
            params["country"] = country

        result = self._make_request("/geocode.json", params)

        if "error" in result:
            return self._build_geocode_failure(error=result["error"])

        response = result.get("Response", {})
        view = response.get("View", [])
        results = view[0].get("Result", []) if view else []
        accuracy_map = {
            "houseNumber": "ROOFTOP",
            "street": "STREET",
            "intersection": "STREET",
            "postalCode": "CITY",
            "district": "CITY",
            "city": "CITY",
            "state": "REGION",
            "country": "COUNTRY",
        }

        def _extract_feature(result_item: Dict[str, Any]) -> Dict[str, Any]:
            payload = self._extract_address_from_result(result_item)
            location = result_item.get("Location", {})
            display_position = location.get("DisplayPosition", {}) or {}
            lat = display_position.get("Latitude")
            lon = display_position.get("Longitude")
            if lat is not None:
                payload["latitude"] = float(lat)
            if lon is not None:
                payload["longitude"] = float(lon)
            return payload

        return self._feature_geocode_payload(
            features=results,
            extractor=_extract_feature,
            formatted_getter=lambda item: item.get("Location", {})
            .get("Address", {})
            .get("Label", ""),
            accuracy_getter=lambda item, _normalized: accuracy_map.get(
                item.get("MatchQuality", {}).get("MatchLevel", ""), "UNKNOWN"
            ),
            confidence_getter=lambda item, _normalized: float(
                (item.get("MatchQuality", {}).get("Relevance", 0.0) or 0.0) / 100.0
            ),
            missing_error="No address found",
        )

    def reverse_geocode(
        self, latitude: float, longitude: float, **kwargs: Any
    ) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address using HERE."""
        params = {
            "prox": f"{latitude},{longitude},250",
            "mode": "retrieveAddresses",
            "maxresults": 1,
        }
        if "language" in kwargs:
            params["language"] = kwargs["language"]

        result = self._make_request("/geocode.json", params)

        if "error" in result:
            payload = self._build_empty_address_payload(error=result["error"])
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            payload["address_reference"] = None
            return payload

        response = result.get("Response", {})
        view = response.get("View", [])
        if not view:
            payload = self._build_empty_address_payload(error="No address found")
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            payload["address_reference"] = None
            return payload

        results = view[0].get("Result", [])
        if not results:
            payload = self._build_empty_address_payload(error="No address found")
            payload["latitude"] = latitude
            payload["longitude"] = longitude
            payload["address_reference"] = None
            return payload

        best_result = results[0]
        normalized = self._extract_address_from_result(best_result)

        match_quality = best_result.get("MatchQuality", {})
        relevance = match_quality.get("Relevance", 0.0) / 100.0

        location = best_result.get("Location", {})
        address = location.get("Address", {})
        location_id = location.get("LocationId")

        return {
            **normalized,
            "formatted_address": address.get("Label", ""),
            "confidence": relevance,
            "address_reference": (
                str(location_id) if location_id else normalized.get("address_reference")
            ),
            "errors": [],
        }

    def get_address_by_reference(
        self, address_reference: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """Retrieve an address by its LocationId using HERE Geocoding API."""
        if not address_reference:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="address_reference is required",
            )

        params = {"locationid": address_reference}
        if "language" in kwargs:
            params["language"] = kwargs["language"]

        result = self._make_request("/geocode.json", params)

        if "error" in result:
            return self._build_empty_address_payload(
                address_reference=address_reference, error=result["error"]
            )

        response = result.get("Response", {})
        view = response.get("View", [])
        if not view:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="No address found for this LocationId",
            )

        results = view[0].get("Result", [])
        if not results:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="No address found for this LocationId",
            )

        best_result = results[0]
        normalized = self._extract_address_from_result(best_result)

        location = best_result.get("Location", {})
        display_position = location.get("DisplayPosition", {})
        address = location.get("Address", {})
        match_quality = best_result.get("MatchQuality", {})
        relevance = match_quality.get("Relevance", 0.0) / 100.0

        return {
            **normalized,
            "formatted_address": address.get("Label", ""),
            "latitude": display_position.get("Latitude"),
            "longitude": display_position.get("Longitude"),
            "confidence": relevance,
            "address_reference": address_reference,
            "errors": [],
        }

    def _extract_address_from_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from a HERE result."""
        location = result.get("Location", {})
        address = location.get("Address", {})

        address_line1 = ""
        street = address.get("Street", "")
        house_number = address.get("HouseNumber", "")
        if house_number and street:
            address_line1 = f"{house_number} {street}".strip()
        elif street:
            address_line1 = street

        city = address.get("City", "")
        postal_code = address.get("PostalCode", "")
        state = address.get("State", "")
        country = address.get("Country", "").upper()

        # Extract LocationId for reverse lookup
        location_id = location.get("LocationId")

        return {
            "address_line1": address_line1,
            "address_line2": "",
            "address_line3": "",
            "city": city,
            "postal_code": postal_code,
            "state": state,
            "country": country,
            "address_reference": str(location_id) if location_id else None,
        }
