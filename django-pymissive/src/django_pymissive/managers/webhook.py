"""Manager for missive webhooks."""

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
        return self.queryset_class(model=self.model, data=data)
