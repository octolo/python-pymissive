"""Base address verification backend."""

from __future__ import annotations

import time

from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, cast


_ADDRESS_COMPONENT_KEYS = (
    "address_line1",
    "address_line2",
    "address_line3",
    "city",
    "postal_code",
    "state",
    "country",
)


class BaseAddressBackend:
    """Base class for address verification backends.

    Provides a generic interface for address validation, geocoding,
    and normalization across different providers.
    """

    _requests_error_message = "requests package not installed"

    def _build_empty_address_payload(
        self,
        *,
        address_reference: Optional[str] = None,
        error: str = "No data",
        include_coordinates: bool = True,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "address_line1": None,
            "address_line2": None,
            "address_line3": None,
            "city": None,
            "postal_code": None,
            "state": None,
            "country": None,
            "formatted_address": None,
            "confidence": 0.0,
            "errors": [error],
        }
        if include_coordinates:
            payload["latitude"] = None
            payload["longitude"] = None
        if address_reference is not None:
            payload["address_reference"] = address_reference
        return payload

    @staticmethod
    def _build_validation_failure(
        *,
        error: str,
        suggestions: Optional[List[Dict[str, Any]]] = None,
        warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return {
            "is_valid": False,
            "normalized_address": {},
            "confidence": 0.0,
            "suggestions": suggestions or [],
            "warnings": warnings or [],
            "errors": [error],
        }

    @staticmethod
    def _build_geocode_failure(error: str) -> Dict[str, Any]:
        return {
            "latitude": None,
            "longitude": None,
            "accuracy": None,
            "confidence": 0.0,
            "formatted_address": None,
            "errors": [error],
        }

    @staticmethod
    def _build_address_string(
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        address_line3: Optional[str] = None,
        city: Optional[str] = None,
        postal_code: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
    ) -> str:
        """Join address components into a single query string."""
        parts = [
            part
            for part in (
                address_line1,
                address_line2,
                address_line3,
                city,
                postal_code,
                state,
                country,
            )
            if part
        ]
        return ", ".join(parts)

    def _resolve_query_string(
        self,
        query: Optional[str],
        *,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        address_line3: Optional[str] = None,
        city: Optional[str] = None,
        postal_code: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
    ) -> str:
        """Return final query string by preferring free-text query over components."""
        if query:
            return query.strip()
        candidate = self._build_address_string(
            address_line1=address_line1,
            address_line2=address_line2,
            address_line3=address_line3,
            city=city,
            postal_code=postal_code,
            state=state,
            country=country,
        )
        return candidate.strip()

    def _ensure_query_string(
        self,
        *,
        query: Optional[str],
        components: Mapping[str, Any],
        failure_builder: Callable[[str], Dict[str, Any]],
        empty_error: str = "Address query is empty",
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Resolve a query and return a fallback payload when missing."""
        query_string = self._resolve_query_string(query, **components)
        if not query_string:
            return None, failure_builder(empty_error)
        return query_string, None

    def _resolve_components_query(
        self,
        *,
        query: Optional[str],
        context: Mapping[str, Any],
        failure_builder: Callable[[str], Dict[str, Any]],
        empty_error: str = "Address query is empty",
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Extract address components from a context and resolve the query."""
        components = self._extract_address_components(context)
        return self._ensure_query_string(
            query=query,
            components=components,
            failure_builder=failure_builder,
            empty_error=empty_error,
        )

    def _execute_geocode_flow(
        self,
        *,
        query: Optional[str],
        context: Mapping[str, Any],
        failure_builder: Callable[[str], Dict[str, Any]],
        request_callable: Callable[[str], Dict[str, Any]],
        result_handler: Callable[[Dict[str, Any], str], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Common wrapper for geocode flows that share the same structure."""
        query_string, failure = self._resolve_components_query(
            query=query, context=context, failure_builder=failure_builder
        )
        if failure:
            return failure

        # After checking failure is None, query_string is guaranteed to be str
        assert query_string is not None
        result = request_callable(query_string)
        if isinstance(result, dict) and "error" in result:
            return failure_builder(result["error"])

        return result_handler(result, query_string)

    def _feature_validation_payload(
        self,
        *,
        features: List[Dict[str, Any]],
        extractor: Callable[[Dict[str, Any]], Dict[str, Any]],
        formatted_getter: Callable[[Dict[str, Any]], str],
        confidence_getter: Callable[[Dict[str, Any], Dict[str, Any]], float],
        suggestion_formatter: Optional[
            Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
        ] = None,
        valid_threshold: float = 0.5,
        warning_threshold: float = 0.7,
        missing_error: str = "No address found",
        max_suggestions: int = 4,
    ) -> Dict[str, Any]:
        """Build validation payload from generic geocoding features."""

        if not features:
            return self._build_validation_failure(error=missing_error)

        primary_feature = features[0]
        normalized = extractor(primary_feature)
        confidence = float(confidence_getter(primary_feature, normalized))
        normalized["confidence"] = confidence

        is_valid = confidence >= valid_threshold
        suggestions: List[Dict[str, Any]] = []
        if not is_valid and len(features) > 1:
            for feature in features[1 : max_suggestions + 1]:
                suggestion_payload = extractor(feature)
                suggestion_confidence = float(
                    confidence_getter(feature, suggestion_payload)
                )
                if suggestion_formatter:
                    suggestion = suggestion_formatter(feature, suggestion_payload)
                else:
                    suggestion = {
                        "formatted_address": formatted_getter(feature),
                        "confidence": suggestion_confidence,
                        "latitude": suggestion_payload.get("latitude"),
                        "longitude": suggestion_payload.get("longitude"),
                    }
                suggestions.append(suggestion)

        warnings: List[str] = []
        if confidence < warning_threshold:
            warnings.append("Low confidence match")

        return {
            "is_valid": is_valid,
            "normalized_address": normalized,
            "confidence": confidence,
            "suggestions": suggestions,
            "warnings": warnings,
            "errors": [],
            "address_reference": normalized.get("address_reference"),
        }

    def _feature_geocode_payload(
        self,
        *,
        features: List[Dict[str, Any]],
        extractor: Callable[[Dict[str, Any]], Dict[str, Any]],
        formatted_getter: Callable[[Dict[str, Any]], str],
        accuracy_getter: Callable[[Dict[str, Any], Dict[str, Any]], str],
        confidence_getter: Callable[[Dict[str, Any], Dict[str, Any]], float],
        missing_error: str = "No address found",
    ) -> Dict[str, Any]:
        """Build geocode payload from generic geocoding features."""

        if not features:
            return self._build_geocode_failure(error=missing_error)

        feature = features[0]
        normalized = extractor(feature)
        accuracy = accuracy_getter(feature, normalized)
        confidence = confidence_getter(feature, normalized)

        return {
            **normalized,
            "latitude": normalized.get("latitude"),
            "longitude": normalized.get("longitude"),
            "accuracy": accuracy,
            "confidence": confidence,
            "formatted_address": formatted_getter(feature),
            "address_reference": normalized.get("address_reference"),
            "errors": [],
        }

    def _perform_get_request(
        self,
        url: str,
        params: Dict[str, Any],
        *,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute a GET request with consistent error handling."""
        try:
            import requests
        except ImportError:
            return {"error": self._requests_error_message}

        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            return cast(Dict[str, Any], response.json())
        except requests.exceptions.HTTPError as exc:
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", str(exc))
            except Exception:
                error_msg = str(exc)
            return {"error": error_msg}
        except requests.exceptions.RequestException as exc:
            return {"error": str(exc)}

    def _request_json(
        self,
        base_url: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        default_params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Helper to perform GET requests with shared parameter merging."""
        url = f"{base_url}{endpoint}"
        request_params: Dict[str, Any] = dict(default_params or {})
        if params:
            request_params.update(params)
        return self._perform_get_request(url, request_params, headers=headers)

    def _extract_address_components(
        self, context: Mapping[str, Any]
    ) -> Dict[str, Optional[str]]:
        """Extract standardized address component kwargs from a context dict."""
        return {key: context.get(key) for key in _ADDRESS_COMPONENT_KEYS}

    def _rate_limit_with_interval(
        self, attr_name: str, min_interval: float
    ) -> None:
        """Throttle outbound requests by sleeping when needed."""
        last_time = getattr(self, attr_name, 0.0)
        now = time.time()
        if now - last_time < min_interval:
            time.sleep(min_interval - (now - last_time))
        setattr(self, attr_name, time.time())

    name: str = "base"
    display_name: Optional[str] = None
    config_keys: List[str] = []
    required_packages: List[str] = []
    documentation_url: Optional[str] = None
    site_url: Optional[str] = None

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the backend with optional configuration.

        Args:
            config: Configuration dictionary with backend-specific keys.
        """
        self._raw_config: Dict[str, Any] = dict(config or {})
        self._config: Dict[str, Any] = self._filter_config(self._raw_config)

    def _filter_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the subset of config keys declared by the backend."""
        if not self.config_keys:
            return dict(config)
        return {k: v for k, v in config.items() if k in self.config_keys}

    @property
    def label(self) -> str:
        """Human-friendly backend name."""
        if self.display_name:
            return self.display_name
        if self.name:
            return self.name.replace("_", " ").title()
        return self.__class__.__name__

    @property
    def config(self) -> Dict[str, Any]:
        """Access configuration values."""
        return self._config

    def validate_address(
        self,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        address_line3: Optional[str] = None,
        city: Optional[str] = None,
        postal_code: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Validate an address and return normalized/verified data.

        Args:
            address_line1: Street number and name.
            address_line2: Building, apartment, floor (optional).
            address_line3: Additional address info (optional).
            city: City name.
            postal_code: Postal/ZIP code.
            state: State/region/province.
            country: ISO country code (e.g., "FR", "US", "GB").
            **kwargs: Additional address fields.

        Returns:
            Dictionary with validation results:
            - is_valid (bool): Whether the address is valid.
            - normalized_address (dict): Normalized address components.
            - confidence (float): Confidence score (0.0-1.0).
            - suggestions (list): List of suggested addresses if validation fails.
            - warnings (list): List of warnings about the address.
            - errors (list): List of errors if validation fails.
            - address_reference (str, optional): Reference ID for reverse lookup (e.g., place_id, osm_id).
        """
        return {
            "is_valid": False,
            "normalized_address": {},
            "confidence": 0.0,
            "suggestions": [],
            "warnings": ["validate_address() not implemented"],
            "errors": ["Backend does not implement address validation"],
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
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Geocode an address to coordinates (latitude, longitude).

        Args:
            address_line1: Street number and name.
            address_line2: Building, apartment, floor (optional).
            address_line3: Additional address info (optional).
            city: City name.
            postal_code: Postal/ZIP code.
            state: State/region/province.
            country: ISO country code (e.g., "FR", "US", "GB").
            **kwargs: Additional address fields.

        Returns:
            Dictionary with geocoding results:
            - latitude (float): Latitude coordinate.
            - longitude (float): Longitude coordinate.
            - accuracy (str): Accuracy level (e.g., "ROOFTOP", "STREET", "CITY").
            - confidence (float): Confidence score (0.0-1.0).
            - formatted_address (str): Formatted address string.
            - address_reference (str, optional): Reference ID for reverse lookup (e.g., place_id, osm_id).
        """
        return {
            "latitude": None,
            "longitude": None,
            "accuracy": None,
            "confidence": 0.0,
            "formatted_address": None,
            "errors": ["geocode() not implemented"],
        }

    def reverse_geocode(
        self, latitude: float, longitude: float, **kwargs: Any
    ) -> Dict[str, Any]:
        """Reverse geocode coordinates to an address.

        Args:
            latitude: Latitude coordinate.
            longitude: Longitude coordinate.
            **kwargs: Additional options (e.g., language, country bias).

        Returns:
            Dictionary with reverse geocoding results:
            - address_line1 (str): Street number and name.
            - address_line2 (str): Building, apartment, floor (optional).
            - city (str): City name.
            - postal_code (str): Postal/ZIP code.
            - state (str): State/region/province.
            - country (str): ISO country code.
            - formatted_address (str): Formatted address string.
            - confidence (float): Confidence score (0.0-1.0).
            - address_reference (str, optional): Reference ID for reverse lookup (e.g., place_id, osm_id).
        """
        return self._build_empty_address_payload(error="reverse_geocode() not implemented")

    def get_address_by_reference(
        self, address_reference: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """Retrieve an address by its reference ID.

        Args:
            address_reference: Reference ID returned by validate_address, geocode, or reverse_geocode.
            **kwargs: Additional options (e.g., language, country bias).

        Returns:
            Dictionary with address details:
            - address_line1 (str): Street number and name.
            - address_line2 (str): Building, apartment, floor (optional).
            - address_line3 (str): Additional address info (optional).
            - city (str): City name.
            - postal_code (str): Postal/ZIP code.
            - state (str): State/region/province.
            - country (str): ISO country code.
            - formatted_address (str): Formatted address string.
            - latitude (float, optional): Latitude coordinate.
            - longitude (float, optional): Longitude coordinate.
            - confidence (float): Confidence score (0.0-1.0).
            - address_reference (str): The reference ID used for lookup.
            - errors (list): List of errors if lookup fails.
        """
        return self._build_empty_address_payload(
            address_reference=address_reference,
            error="get_address_by_reference() not implemented",
        )

    def normalize_address(
        self,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        address_line3: Optional[str] = None,
        city: Optional[str] = None,
        postal_code: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Normalize address components to standard format.

        Args:
            address_line1: Street number and name.
            address_line2: Building, apartment, floor (optional).
            address_line3: Additional address info (optional).
            city: City name.
            postal_code: Postal/ZIP code.
            state: State/region/province.
            country: ISO country code (e.g., "FR", "US", "GB").
            **kwargs: Additional address fields.

        Returns:
            Dictionary with normalized address components:
            - address_line1 (str): Normalized street address.
            - address_line2 (str): Normalized building/apartment info.
            - city (str): Normalized city name.
            - postal_code (str): Normalized postal code.
            - state (str): Normalized state/region.
            - country (str): ISO country code.
            - formatted_address (str): Complete formatted address.
        """
        return {
            "address_line1": address_line1 or "",
            "address_line2": address_line2 or "",
            "address_line3": address_line3 or "",
            "city": city or "",
            "postal_code": postal_code or "",
            "state": state or "",
            "country": country or "",
            "formatted_address": self._format_address(
                address_line1, address_line2, city, postal_code, state, country
            ),
        }

    def _format_address(
        self,
        address_line1: Optional[str],
        address_line2: Optional[str],
        city: Optional[str],
        postal_code: Optional[str],
        state: Optional[str],
        country: Optional[str],
    ) -> str:
        """Format address components into a single string."""
        parts = []
        if address_line1:
            parts.append(address_line1)
        if address_line2:
            parts.append(address_line2)
        city_line = []
        if postal_code:
            city_line.append(postal_code)
        if city:
            city_line.append(city)
        if city_line:
            parts.append(" ".join(city_line))
        if state:
            parts.append(state)
        if country:
            parts.append(country)
        return ", ".join(parts)

    def check_package_and_config(self) -> Dict[str, Any]:
        """Check if required packages are installed and config is valid.

        Returns:
            Dictionary with:
            - packages (dict): Status of required packages.
            - config (dict): Status of configuration keys.
        """
        import importlib

        packages = {}
        for pkg in self.required_packages:
            try:
                importlib.import_module(pkg)
                packages[pkg] = "installed"
            except ImportError:
                packages[pkg] = "missing"

        config_status = {}
        for key in self.config_keys:
            config_status[key] = "present" if key in self._config else "missing"

        return {
            "packages": packages,
            "config": config_status,
        }
