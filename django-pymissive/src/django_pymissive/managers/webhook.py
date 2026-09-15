"""Manager for missive webhooks."""

from urllib.parse import urlparse

from virtualqueryset.managers import VirtualManager


class MissiveWebhookManager(VirtualManager):
    """Manager for missive webhooks (provider API, no table)."""

    def _rows_for_provider(self, provider) -> list:
        backend = getattr(provider, "_provider", None)
        if backend is None:
            return []
        backend.call_service("retrieve_webhooks")
        data = backend.get_service_normalize("retrieve_webhooks") or []
        rows = []
        for item in data:
            row = dict(item)
            row["provider"] = provider
            if url := row.get("url"):
                parsed = urlparse(url)
                row.setdefault("scheme", parsed.scheme or "https")
                row.setdefault("domain", parsed.netloc)
            rows.append(row)
        return rows

    def get_queryset(self, provider=None):
        """``provider=None`` is empty (``all()`` must not hit every API).

        Pass a provider name/instance, or use :meth:`all_providers`.
        """
        if provider is None:
            return self.queryset_class(model=self.model, data=[])
        if isinstance(provider, str):
            from ..models.provider import MissiveProviderModel

            provider = MissiveProviderModel.objects.get(name=provider)
        return self.queryset_class(
            model=self.model, data=self._rows_for_provider(provider)
        )

    def all_providers(self):
        """One virtual queryset with every provider's webhooks."""
        from ..models.provider import MissiveProviderModel

        data = []
        for provider in MissiveProviderModel.objects.all():
            try:
                data.extend(self._rows_for_provider(provider))
            except Exception:
                continue
        return self.queryset_class(model=self.model, data=data)
