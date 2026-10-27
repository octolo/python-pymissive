from typing import Any, cast

from .types import MailevaMixinTypingBase


class MailevaWebhookMixin(MailevaMixinTypingBase):
    def _create_webhook_postal(self, webhook_data: dict[str, Any], *, product: str) -> str | None:
        webhook_url = cast(str, webhook_data.get("url"))
        events = list([event for event in self.events_association.keys() if event.startswith("ON_")])
        resource_types = self.get_resource_types(product)
        return self._create_webhook_api(webhook_url, events, resource_types)

    def create_webhook_letter(self, webhook_data: dict[str, Any]) -> str | None:
        return self._create_webhook_postal(webhook_data, product="letter")

    def create_webhook_registered_letter(self, webhook_data: dict[str, Any]) -> str | None:
        return self._create_webhook_postal(webhook_data, product="registered_letter")

    def _retrieve_webhooks_registered_letter(self) -> list[dict[str, Any]]:
        webhooks = self.retrieve_webhooks()
        resource_types = self.get_resource_types("registered_letter") + self.get_resource_types("letter")
        return [webhook for webhook in webhooks if webhook.get("resource_type") in resource_types]

    def _raw_id_from_webhook_id(self, webhook_id: str | None) -> str | None:
        """Extract raw provider id from normalized webhook_id (e.g. 'maileva-123' -> '123')."""
        if not webhook_id:
            return None
        parts = str(webhook_id).split("-", 1)
        return parts[1] if len(parts) > 1 else parts[0]

    def _webhook_url_from_data(self, webhook_data: dict[str, Any]) -> str | None:
        url = webhook_data.get("url") or webhook_data.get("callback_url")
        if url:
            return url
        raw_id = self._raw_id_from_webhook_id(webhook_data.get("webhook_id") or webhook_data.get("id"))
        if not raw_id:
            return None
        for webhook in self.retrieve_webhooks():
            if str(webhook.get("id")) == str(raw_id):
                return webhook.get("callback_url")
        return None

    def delete_webhook_letter(self, webhook_data: dict[str, Any]) -> bool:
        return self._delete_webhook_postal(webhook_data, product="letter")

    def delete_webhook_registered_letter(self, webhook_data: dict[str, Any]) -> bool:
        return self._delete_webhook_postal(webhook_data, product="registered_letter")

    def _delete_webhook_postal(self, webhook_data: dict[str, Any], *, product: str) -> bool:
        url = self._webhook_url_from_data(webhook_data)
        if not url:
            raise ValueError("Cannot delete webhook: no URL and could not derive from webhook_id")
        return self.delete_webhooks(product, url)

    def update_webhook_letter(self, webhook_data: dict[str, Any]) -> bool:
        return self._update_webhook_postal(webhook_data, product="letter")

    def update_webhook_registered_letter(self, webhook_data: dict[str, Any]) -> bool:
        return self._update_webhook_postal(webhook_data, product="registered_letter")

    def _update_webhook_postal(self, webhook_data: dict[str, Any], *, product: str) -> bool:
        new_url = webhook_data.get("url") or webhook_data.get("callback_url")
        search_url = new_url or self._webhook_url_from_data(webhook_data)
        if not search_url:
            raise ValueError("Cannot update webhook: no URL and could not derive from webhook_id")
        return self.update_webhooks(
            product,
            search_url,
            new_url or search_url,
        )
