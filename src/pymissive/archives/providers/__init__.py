"""Provider discovery and registry helpers."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Type

from .apn import APNProvider
from .ar24 import AR24Provider
from .base import BaseProvider, BaseProviderCommon
from .brevo import BrevoProvider
from .certeurope import CerteuropeProvider
from .django_email import DjangoEmailProvider
from .fcm import FCMProvider
from .laposte import LaPosteProvider
from .maileva import MailevaProvider
from .mailgun import MailgunProvider
from .messenger import MessengerProvider
from .notification import InAppNotificationProvider
from .sendgrid import SendGridProvider
from .ses import SESProvider
from .signal import SignalProvider
from .slack import SlackProvider
from .smspartner import SMSPartnerProvider
from .teams import TeamsProvider
from .telegram import TelegramProvider
from .twilio import TwilioProvider
from .vonage import VonageProvider


class ProviderImportError(RuntimeError):
    """Raised when a provider cannot be imported."""


def load_provider_class(import_path: str) -> Type[BaseProviderCommon]:
    """Dynamically import a provider class using dotted notation."""
    module_path, _, class_name = import_path.rpartition(".")
    if not module_path:
        raise ProviderImportError(f"Invalid provider path: {import_path}")

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ProviderImportError(f"Cannot import module {module_path}") from exc

    try:
        provider_class = getattr(module, class_name)
    except AttributeError as exc:
        raise ProviderImportError(
            f"Module {module_path} does not define {class_name}"
        ) from exc

    if not issubclass(provider_class, BaseProviderCommon):
        raise ProviderImportError(
            f"{import_path} is not a subclass of BaseProviderCommon"
        )

    return provider_class  # type: ignore[return-value,no-any-return]


def get_provider_name_from_path(provider_path: str) -> str:
    """Return shortcut name derived from the full provider path."""
    if not provider_path:
        return "custom"

    if "." not in provider_path:
        return provider_path.lower()

    parts = provider_path.split(".")
    if len(parts) >= 3 and parts[0] == "pymissive" and parts[1] == "providers":
        return parts[2].lower()

    class_name = parts[-1]
    provider_name = class_name.replace("Provider", "").lower()
    return provider_name or "custom"


@dataclass
class ProviderRegistry:
    """In-memory registry for provider classes."""

    providers: Dict[str, Type[BaseProviderCommon]] = field(default_factory=dict)

    def register(self, provider_path: str) -> None:
        """Import and register a provider class."""
        provider_class = load_provider_class(provider_path)
        provider_name = get_provider_name_from_path(provider_path)
        self.providers[provider_name] = provider_class

    def register_many(self, provider_paths: Iterable[str]) -> None:
        """Register a collection of providers."""
        for provider_path in provider_paths:
            self.register(provider_path)

    def instantiate(self, provider_name: str, *args, **kwargs) -> BaseProviderCommon:
        """Instantiate a provider by its registered short name."""
        try:
            provider_class = self.providers[provider_name]
        except KeyError as exc:
            raise ProviderImportError(
                f"Provider '{provider_name}' is not registered."
            ) from exc
        return provider_class(*args, **kwargs)

    def group_by_type(self) -> Dict[str, List[str]]:
        """Group registered providers by their supported missive types."""
        mapping: Dict[str, List[str]] = {}
        for name, provider_class in self.providers.items():
            for missive_type in provider_class.supported_types:
                mapping.setdefault(missive_type, []).append(name)
        return mapping

    def group_paths_by_type(self) -> Dict[str, List[str]]:
        """Group registered providers by type, returning import paths."""
        mapping: Dict[str, List[str]] = {}
        for provider_class in self.providers.values():
            import_path = f"{provider_class.__module__}.{provider_class.__name__}"
            for missive_type in provider_class.supported_types:
                mapping.setdefault(missive_type, []).append(import_path)
        return mapping


def build_registry(provider_paths: Sequence[str]) -> ProviderRegistry:
    """Convenience helper to create and populate a registry."""
    registry = ProviderRegistry()
    registry.register_many(provider_paths)
    return registry


__all__ = [
    "BaseProvider",
    "BaseProviderCommon",
    "ProviderImportError",
    "ProviderRegistry",
    "APNProvider",
    "AR24Provider",
    "BrevoProvider",
    "CerteuropeProvider",
    "FCMProvider",
    "DjangoEmailProvider",
    "InAppNotificationProvider",
    "LaPosteProvider",
    "MailevaProvider",
    "MailgunProvider",
    "MessengerProvider",
    "SendGridProvider",
    "SESProvider",
    "SignalProvider",
    "SlackProvider",
    "SMSPartnerProvider",
    "TeamsProvider",
    "TelegramProvider",
    "TwilioProvider",
    "VonageProvider",
    "build_registry",
    "get_provider_name_from_path",
    "load_provider_class",
]
