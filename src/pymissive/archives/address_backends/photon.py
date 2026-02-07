"""Photon (Komoot) address verification backend."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAddressBackend


class PhotonAddressBackend(BaseAddressBackend):
    """Photon (Komoot) Geocoding API backend for address verification.

    Completely free, no API key required. Fast geocoding based on OpenStreetMap data.
    Provided by Komoot.
    """

    name = "photon"
    display_name = "Photon (Komoot)"
    config_keys = ["PHOTON_BASE_URL"]
    required_packages = ["requests"]
    documentation_url = "https://photon.komoot.io/"
    site_url = "https://photon.komoot.io"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Photon backend.

        Args:
            config: Optional configuration dict with:
                - PHOTON_BASE_URL: Custom Photon server URL (default: official)
        """
        super().__init__(config)
        self._base_url = self._config.get("PHOTON_BASE_URL", "https://photon.komoot.io")

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the Photon API."""
        return self._request_json(self._base_url, endpoint, params)

    def validate_address(  # noqa: C901
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
        """Validate an address using Photon."""
        query_string, failure = self._resolve_components_query(
            query=query,
            context=locals(),
            failure_builder=lambda msg: self._build_validation_failure(error=msg),
        )
        if failure:
            return failure

        params = {"q": query_string, "limit": 5}
        if country:
            params["osm_tag"] = f"place:country={country}"

        result = self._make_request("/api", params)

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

        def _confidence_from_feature(
            feature: Dict[str, Any], normalized: Dict[str, Any]
        ) -> float:
            properties = feature.get("properties", {})
            confidence_score = 0.0
            if properties.get("housenumber") and properties.get("street"):
                confidence_score = 0.9
            elif properties.get("street"):
                confidence_score = 0.7
            elif properties.get("city") or properties.get("postcode"):
                confidence_score = 0.5
            importance = properties.get("importance")
            if importance is not None:
                confidence_score = min(float(importance) * 2.0, 1.0)
            return confidence_score

        payload = self._feature_validation_payload(
            features=features,
            extractor=_extract_with_coordinates,
            formatted_getter=lambda feature: feature.get("properties", {}).get("name", ""),
            confidence_getter=_confidence_from_feature,
            suggestion_formatter=lambda feature, normalized_suggestion: {
                "formatted_address": feature.get("properties", {}).get("name", ""),
                "confidence": float(
                    min(
                        (feature.get("properties", {}).get("importance", 0.0) or 0.0) * 2.0,
                        1.0,
                    )
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
            importance = features[0].get("properties", {}).get("importance")
            if importance is not None and importance < 0.5:
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
        """Geocode an address to coordinates using Photon."""

        def _request(query_string: str) -> Dict[str, Any]:
            params = {"q": query_string, "limit": 1}
            if country:
                params["osm_tag"] = f"place:country={country}"
            return self._make_request("/api", params)

        def _handle(result: Dict[str, Any], _query: str) -> Dict[str, Any]:
            features = result.get("features", [])

            def _extract_with_coordinates(feature: Dict[str, Any]) -> Dict[str, Any]:
                payload = self._extract_address_from_feature(feature)
                coords = feature.get("geometry", {}).get("coordinates", [])
                if len(coords) >= 2:
                    payload["latitude"] = float(coords[1])
                    payload["longitude"] = float(coords[0])
                return payload

            def _accuracy_from_feature(
                feature: Dict[str, Any], _normalized: Dict[str, Any]
            ) -> str:
                properties = feature.get("properties", {})
                osm_type = properties.get("osm_type", "")
                osm_key = properties.get("osm_key", "")
                accuracy_map = {
                    "node": "ROOFTOP" if osm_key == "place" else "STREET",
                    "way": "STREET",
                    "relation": "CITY",
                }
                return accuracy_map.get(osm_type, "UNKNOWN")

            return self._feature_geocode_payload(
                features=features,
                extractor=_extract_with_coordinates,
                formatted_getter=lambda feature: feature.get("properties", {}).get("name", ""),
                accuracy_getter=_accuracy_from_feature,
                confidence_getter=lambda feature, _normalized: float(
                    min((feature.get("properties", {}).get("importance", 0.0) or 0.0) * 2.0, 1.0)
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
        """Reverse geocode coordinates to an address using Photon."""
        params = {"lat": str(latitude), "lon": str(longitude), "limit": 1}
        if "language" in kwargs:
            params["lang"] = kwargs["language"]

        result = self._make_request("/reverse", params)

        if "error" in result:
            return self._build_empty_address_payload(error=result["error"])

        features = result.get("features", [])
        if not features:
            return self._build_empty_address_payload(error="No address found")

        feature = features[0]
        normalized = self._extract_address_from_feature(feature)

        properties = feature.get("properties", {})
        importance = properties.get("importance", 0.0)
        confidence = min(importance * 2.0, 1.0)

        return {
            **normalized,
            "formatted_address": properties.get("name", ""),
            "confidence": confidence,
            "address_reference": normalized.get("address_reference"),
            "errors": [],
        }

    def get_address_by_reference(self, address_reference: str, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve an address by its OSM reference (osm_type:osm_id).

        Note: Photon API does not directly support lookup by OSM ID.
        This implementation attempts to use the reference but may not work
        for all cases. Consider using Nominatim backend for reliable ID-based lookups.
        """
        if not address_reference:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="address_reference is required",
            )

        if ":" not in address_reference:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="Invalid OSM reference format. Expected 'osm_type:osm_id'",
            )

        parts = address_reference.split(":", 1)
        if len(parts) != 2:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="Invalid OSM reference format",
            )

        osm_type, osm_id_str = parts
        try:
            osm_id = int(osm_id_str)
        except (ValueError, TypeError):
            return self._build_empty_address_payload(
                address_reference=address_reference, error="Invalid OSM ID format"
            )

        params = {"osm_ids": f"{osm_type},{osm_id}", "limit": 1}
        if "language" in kwargs:
            params["lang"] = kwargs["language"]

        result = self._make_request("/api", params)

        if "error" in result:
            return self._build_empty_address_payload(
                address_reference=address_reference, error=result["error"]
            )

        features = result.get("features", [])
        if not features:
            return self._build_empty_address_payload(
                address_reference=address_reference,
                error="No address found for this OSM reference",
            )

        feature = features[0]
        normalized = self._extract_address_from_feature(feature)

        coordinates = feature.get("geometry", {}).get("coordinates", [])
        properties = feature.get("properties", {})
        importance = properties.get("importance", 0.0)
        confidence = min(importance * 2.0, 1.0)

        return {
            **normalized,
            "formatted_address": properties.get("name", ""),
            "latitude": coordinates[1] if len(coordinates) >= 2 else None,
            "longitude": coordinates[0] if len(coordinates) >= 1 else None,
            "confidence": confidence,
            "address_reference": address_reference,
            "errors": [],
        }

    def _extract_address_from_feature(self, feature: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address components from a Photon feature."""
        properties = feature.get("properties", {})

        address_line1 = ""
        house_number = properties.get("housenumber", "")
        street = properties.get("street", "")
        if house_number and street:
            address_line1 = f"{house_number} {street}".strip()
        elif street:
            address_line1 = street

        city = properties.get("city") or properties.get("town") or properties.get("village") or ""
        postal_code = properties.get("postcode", "")
        state = properties.get("state", "")
        country = properties.get("countrycode", "").upper()

        # Extract OSM reference (osm_id + osm_type for reverse lookup)
        osm_id = properties.get("osm_id")
        osm_type = properties.get("osm_type")
        address_reference = None
        if osm_id is not None and osm_type:
            # Format: "osm_type:osm_id" for reverse lookup
            address_reference = f"{osm_type}:{osm_id}"

        return {
            "address_line1": address_line1,
            "address_line2": "",
            "address_line3": "",
            "city": city,
            "postal_code": postal_code,
            "state": state,
            "country": country,
            "address_reference": address_reference,
        }
