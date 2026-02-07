"""Missive sending with automatic provider fallback."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Union

from .helpers import get_provider_paths_from_config
from .missive import Missive
from .providers import ProviderImportError, load_provider_class

logger = logging.getLogger(__name__)

# Type alias for providers_config: can be a list of paths or a dict {path: config}
ProvidersConfig = Union[Sequence[str], Dict[str, Dict[str, Any]]]


class MissiveSender:
    """Sends missives with automatic provider fallback."""

    def __init__(
        self,
        providers_config: Optional[ProvidersConfig] = None,
        default_config: Optional[Dict[str, Any]] = None,
        sandbox: bool = False,
    ):
        """Initialize sender with optional provider configuration.

        Args:
            providers_config: Either:
                - List of provider import paths (e.g., ["pymissive.providers.brevo.BrevoProvider"])
                - Dict mapping provider paths to their configs (e.g., {"path": {"API_KEY": "value"}})
            default_config: Default configuration dict merged with provider-specific configs
            sandbox: If True, forces sandbox mode for all providers (no real sends)
        """
        self.providers_config = providers_config
        self.default_config = default_config or {}
        self.sandbox = sandbox

        # Extract provider paths if config is a dict
        if isinstance(providers_config, dict):
            self._provider_configs = providers_config
            self._provider_paths = list(providers_config.keys())
        else:
            self._provider_configs = {}
            self._provider_paths = list(providers_config) if providers_config else []

    # -------------------------------
    # Geo helpers
    # -------------------------------
    @staticmethod
    def _geo_attr_for_type(mtype: str) -> str:
        """Return the geographic coverage attribute name for a missive type."""
        base = (mtype or "").strip().lower().replace(" ", "_")
        return f"{base}_geographic_coverage"

    @staticmethod
    def _get_destination(m: Missive) -> Dict[str, Optional[str]]:
        opts = m.provider_options or {}
        country = (
            opts.get("country")
            or opts.get("country_code")
            or opts.get("destination_country")
        )
        continent = opts.get("continent") or opts.get("destination_continent")
        recipient = getattr(m, "recipient", None)
        metadata = getattr(recipient, "metadata", None) if recipient else None
        if not country and isinstance(metadata, dict):
            country = metadata.get("country_code") or metadata.get("country")
            if not continent:
                continent = metadata.get("continent") or metadata.get("region")
        if isinstance(country, str):
            country = country.strip()
        if isinstance(continent, str):
            continent = continent.strip()
        return {"country": country, "continent": continent}

    @staticmethod
    def _tokenize_geo(value: Any) -> Union[str, list[str]]:
        if value is None:
            return "*"
        if isinstance(value, str):
            if value.strip() == "*":
                return "*"
            if "," in value:
                return [v.strip() for v in value.split(",") if v.strip()]
            return [value.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(v).strip() for v in value if str(v).strip()]
        return []

    @staticmethod
    def _geo_allows(
        geo_value: Any, *, country: Optional[str], continent: Optional[str]
    ) -> bool:
        tokens = MissiveSender._tokenize_geo(geo_value)
        if tokens == "*":
            return True
        token_set_lower = {t.lower() for t in tokens}
        token_set_upper = {t.upper() for t in tokens}
        if continent and continent.strip() and continent.lower() in token_set_lower:
            return True
        if country and country.strip():
            c = country.strip()
            if c.lower() in token_set_lower or c.upper() in token_set_upper:
                return True
        return False

    def get_provider_paths(self, missive: Missive) -> List[str]:
        """Return ordered list of provider paths to try (by priority).

        Providers are determined from the configuration passed to the sender.
        If no providers_config is provided, returns empty list.
        """
        if missive.provider:
            logger.info("Missive: Explicit provider '%s'", missive.provider)
            return [missive.provider]

        if not self.providers_config:
            raise ValueError(
                f"No providers_config provided and no explicit provider set for {missive.missive_type}"
            )

        # Use provider paths (extracted from dict if needed)
        providers_by_type = get_provider_paths_from_config(self._provider_paths)
        provider_paths = providers_by_type.get(missive.missive_type.upper())

        if not provider_paths:
            raise ValueError(
                f"No provider configured for {missive.missive_type}. "
                f"Available types: {list(providers_by_type.keys())}"
            )

        logger.info(
            "Missive: Configured providers for %s: %s",
            missive.missive_type,
            provider_paths,
        )
        return provider_paths

    def get_provider_config(self, provider_path: str) -> Dict[str, Any]:
        """Get configuration for a specific provider, merged with default config.

        Args:
            provider_path: Full import path of the provider

        Returns:
            Merged configuration dict (provider-specific config takes precedence)
        """
        provider_config = self._provider_configs.get(provider_path, {})
        # Merge: default_config first, then provider-specific config (provider wins)
        return {**self.default_config, **provider_config}

    def _attempt_send(
        self,
        provider_path: str,
        *,
        missive: Missive,
        geo_attr: str,
        destination: Dict[str, Optional[str]],
        provider_kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Attempt sending with one provider and return a structured result."""
        try:
            provider_class = load_provider_class(provider_path)
            provider_name = provider_class.__name__
        except ProviderImportError as e:
            return {
                "provider": provider_path,
                "provider_name": provider_path.split(".")[-1],
                "status": "import_error",
                "error": str(e),
            }

        # Geo check
        geo_value = getattr(provider_class, geo_attr, None)
        if geo_value is None:
            legacy_attr = geo_attr.replace("_geographic_coverage", "_geo")
            geo_value = getattr(provider_class, legacy_attr, "*")
        if not self._geo_allows(
            geo_value,
            country=destination["country"],
            continent=destination["continent"],
        ):
            return {
                "provider": provider_name,
                "provider_name": provider_name,
                "status": "skipped_geo",
                "geo": {geo_attr: geo_value, **destination},
            }

        # Instantiate and send
        try:
            provider_config = self.get_provider_config(provider_path)
            provider = provider_class(
                missive=missive,
                config=provider_config,
                **provider_kwargs,
            )
            if hasattr(provider, "send"):
                success = provider.send()  # type: ignore[attr-defined]
            else:
                raise RuntimeError(
                    f"Provider {provider_path} does not have send() method"
                )
            return {
                "provider": provider_name,
                "provider_name": provider_name,
                "status": "success" if success else "failed",
            }
        except Exception as e:
            return {
                "provider": provider_path,
                "provider_name": provider_class.__name__,
                "status": "exception",
                "error": str(e),
            }

    def send(
        self,
        missive: Missive,
        enable_fallback: bool = True,
        **provider_kwargs: Any,
    ) -> bool:
        """Send missive via appropriate provider with automatic fallback.

        If sandbox mode is enabled, forces sandbox=True in provider_options.

        Args:
            missive: Missive object to send
            enable_fallback: If True, try next provider on failure
            **provider_kwargs: Additional kwargs to pass to provider constructor

        Returns:
            True if sent successfully, False otherwise

        Raises:
            RuntimeError: If all providers fail and enable_fallback is True
            ValueError: If no providers are configured
        """
        # Force sandbox mode if enabled globally
        if self.sandbox:
            if not missive.provider_options:
                missive.provider_options = {}
            # Force sandbox=True (unless explicitly disabled)
            if "sandbox" not in missive.provider_options:
                missive.provider_options["sandbox"] = True
        if not missive.can_send():
            logger.warning("Missive: Cannot be sent (can_send()=False)")
            return False

        provider_paths = self.get_provider_paths(missive)

        if not provider_paths:
            raise ValueError(f"No provider configured for {missive.missive_type}")

        total_attempts = len(provider_paths)
        logger.info(
            "Missive: Attempting to send with %d available provider(s)",
            total_attempts,
        )

        last_error = None
        attempts = []

        destination = self._get_destination(missive)
        geo_attr = self._geo_attr_for_type(missive.missive_type)

        for index, provider_path in enumerate(provider_paths, 1):
            result = self._attempt_send(
                provider_path,
                missive=missive,
                geo_attr=geo_attr,
                destination=destination,
                provider_kwargs=provider_kwargs,
            )
            status = result.get("status")
            provider_name = result.get("provider_name", provider_path)
            logger.info(
                "Missive: Attempt %d/%d with %s", index, total_attempts, provider_name
            )

            if status == "skipped_geo":
                logger.info(
                    "Missive: Skipping %s — geo not allowed (attempt %d/%d)",
                    provider_name,
                    index,
                    total_attempts,
                )
                result["attempt"] = index
                attempts.append(result)
                continue
            if status == "import_error":
                msg = f"Provider '{provider_path}' not found: {result.get('error')}"
                logger.error("Missive: %s", msg)
                last_error = msg
                result["attempt"] = index
                attempts.append(result)
                if not enable_fallback:
                    raise ValueError(msg)
                continue
            if status == "exception":
                msg = f"Error sending with {provider_path}: {result.get('error')}"
                logger.error("Missive: %s", msg)
                last_error = msg
                result["attempt"] = index
                attempts.append(result)
                if not enable_fallback:
                    raise RuntimeError(msg)
                continue
            if status == "success":
                logger.info(
                    "Missive: ✅ Sent successfully via %s (attempt %d/%d)",
                    provider_name,
                    index,
                    total_attempts,
                )
                attempts.append(
                    {"provider": provider_name, "status": "success", "attempt": index}
                )
                missive.provider = provider_path
                return True
            if status == "failed":
                logger.warning("Missive: ❌ Failed with %s", provider_name)
                attempts.append(
                    {"provider": provider_name, "status": "failed", "attempt": index}
                )
                if not enable_fallback:
                    raise RuntimeError(f"Send failed with {provider_name}")
                continue

        # If we get here, all providers failed
        error_summary = "All providers failed. "
        error_summary += f"Attempts: {attempts}. "
        if last_error:
            error_summary += f"Last error: {last_error}"

        logger.error(error_summary)
        raise RuntimeError(error_summary)
