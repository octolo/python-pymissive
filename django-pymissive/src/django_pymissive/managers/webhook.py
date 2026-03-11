"""Manager for missive webhooks."""

from urllib.parse import urlparse

from virtualqueryset.managers import VirtualManager


class MissiveWebhookManager(VirtualManager):
    """Manager for missive webhooks."""

    def get_queryset(self, provider=None):
        if provider is None:
            data = []
        else:
            if isinstance(provider, str):
                from ..models.provider import MissiveProviderModel

                provider = MissiveProviderModel.objects.get(name=provider)
            provider._provider.call_service("get_webhooks")
            data = provider._provider.get_service_normalize("get_webhooks")
            for item in data:
                item["provider"] = provider
                # Derive scheme and domain from url for edit form
                if url := item.get("url"):
                    parsed = urlparse(url)
                    item.setdefault("scheme", parsed.scheme or "https")
                    item.setdefault("domain", parsed.netloc)
        return self.queryset_class(model=self.model, data=data)
