"""Utilities shared by Pelias-compatible address backends."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Protocol

    class PeliasBackendProtocol(Protocol):
        """Protocol for backends that use PeliasFeatureMixin."""

        def _build_empty_address_payload(
            self, *, error: str
        ) -> Dict[str, Any]:
            ...

        def _extract_address_from_feature(
            self, feature: Dict[str, Any]
        ) -> Dict[str, Any]:
            ...

        def _make_request(
            self, endpoint: str, params: Dict[str, Any]
        ) -> Dict[str, Any]:
            ...

        def _build_geocode_failure(self, *, error: str) -> Dict[str, Any]:
            ...

        def _feature_geocode_payload(
            self,
            *,
            features: list[Dict[str, Any]],
            extractor: Callable[[Dict[str, Any]], Dict[str, Any]],
            formatted_getter: Callable[[Dict[str, Any]], str],
            accuracy_getter: Callable[[Dict[str, Any], Dict[str, Any]], str],
            confidence_getter: Callable[[Dict[str, Any], Dict[str, Any]], float],
            missing_error: str,
        ) -> Dict[str, Any]:
            ...

        def _build_validation_failure(self, *, error: str) -> Dict[str, Any]:
            ...

        def _feature_validation_payload(
            self,
            *,
            features: list[Dict[str, Any]],
            extractor: Callable[[Dict[str, Any]], Dict[str, Any]],
            formatted_getter: Callable[[Dict[str, Any]], str],
            confidence_getter: Callable[[Dict[str, Any], Dict[str, Any]], float],
            suggestion_formatter: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
            valid_threshold: float,
            warning_threshold: float,
            missing_error: str,
            max_suggestions: int,
        ) -> Dict[str, Any]:
            ...


FeatureDict = Dict[str, Any]
FormattedGetter = Callable[[FeatureDict], str]
SuggestionFormatter = Callable[[FeatureDict, Dict[str, Any]], Dict[str, Any]]


class PeliasFeatureMixin:
    """Helper methods for backends built on Pelias responses."""

    def _pelias_feature_payload(  # pragma: no cover - thin helper
        self,
        features: Sequence[FeatureDict],
        *,
        formatted_getter: FormattedGetter,
        missing_error: str = "No address found",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Normalize Pelias features into a payload compatible with BaseAddressBackend."""

        if not features:
            empty_payload = self._build_empty_address_payload(error=missing_error)  # type: ignore[attr-defined]
            if latitude is not None:
                empty_payload["latitude"] = latitude
            if longitude is not None:
                empty_payload["longitude"] = longitude
            empty_payload["address_reference"] = None
            return empty_payload  # type: ignore[no-any-return]

        best_match = features[0]
        normalized = self._extract_address_from_feature(best_match)  # type: ignore[attr-defined]

        payload: Dict[str, Any] = {
            **normalized,
            "formatted_address": formatted_getter(best_match),
            "confidence": normalized.get("confidence", 0.0),
            "address_reference": normalized.get("address_reference"),
            "errors": [],
        }

        if latitude is not None:
            payload["latitude"] = normalized.get("latitude", latitude)
        if longitude is not None:
            payload["longitude"] = normalized.get("longitude", longitude)

        return payload

    def _pelias_geocode_request(
        self,
        *,
        endpoint: str,
        params: Dict[str, Any],
        formatted_getter: FormattedGetter,
        missing_error: str = "No address found",
        accuracy: str = "ROOFTOP",
    ) -> Dict[str, Any]:
        """Perform a Pelias geocode request and normalize the result."""
        result = self._make_request(endpoint, params)  # type: ignore[attr-defined]

        if "error" in result:
            return self._build_geocode_failure(error=result["error"])  # type: ignore[attr-defined,no-any-return]

        features = result.get("features", [])

        def _extract(feature: FeatureDict) -> Dict[str, Any]:
            payload = self._extract_address_from_feature(feature)  # type: ignore[attr-defined]
            payload["formatted_address"] = formatted_getter(feature)
            payload.setdefault("accuracy", accuracy)
            return payload  # type: ignore[no-any-return]

        return self._feature_geocode_payload(  # type: ignore[attr-defined,no-any-return]
            features=features,
            extractor=_extract,
            formatted_getter=formatted_getter,
            accuracy_getter=lambda _feature, _normalized: accuracy,
            confidence_getter=lambda _feature, normalized: float(
                normalized.get("confidence", 0.0)
            ),
            missing_error=missing_error,
        )

    def _pelias_validate_autocomplete(
        self,
        result: Dict[str, Any],
        *,
        formatted_getter: FormattedGetter,
        suggestion_formatter: Optional[SuggestionFormatter] = None,
        missing_error: str = "No address found",
        confidence_threshold: float = 0.5,
        warning_threshold: float = 0.7,
        suggestion_limit: int = 5,
    ) -> Dict[str, Any]:
        """Normalize Pelias autocomplete responses for validate_address."""

        if "error" in result:
            return self._build_validation_failure(error=result["error"])  # type: ignore[attr-defined,no-any-return]

        features = result.get("features", [])

        formatter = suggestion_formatter or (
            lambda feature, suggestion: {
                "formatted_address": formatted_getter(feature),
                "confidence": suggestion.get("confidence", 0.0),
                "latitude": suggestion.get("latitude"),
                "longitude": suggestion.get("longitude"),
            }
        )

        return self._feature_validation_payload(  # type: ignore[attr-defined,no-any-return]
            features=list(features),
            extractor=self._extract_address_from_feature,  # type: ignore[attr-defined]
            formatted_getter=formatted_getter,
            confidence_getter=lambda _feature, normalized: float(
                normalized.get("confidence", 0.0)
            ),
            suggestion_formatter=formatter,
            valid_threshold=confidence_threshold,
            warning_threshold=warning_threshold,
            missing_error=missing_error,
            max_suggestions=suggestion_limit,
        )
