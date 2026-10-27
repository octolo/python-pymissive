from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import requests


if TYPE_CHECKING:

    class MailevaMixinTypingBase:
        """Static contract shared by the Maileva mixins."""

        endpoints: dict[str, str]
        events_association: dict[str, str]
        proof_keys: list[str]
        registered_letter_proof_keys: list[str]
        resource_types: dict[str, str]

        def _get_config_or_env(self, key: str, default: Any = None) -> Any: ...

        def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response: ...

        def _raise_for_response(self, response: requests.Response, context: str) -> None: ...

        def _normalize_archiving_duration(self, value: Any) -> int: ...

        def get_endpoint(self, endpoint: str, prefix: str = "api", *, product: str | None = None) -> str: ...

        def get_resource_types(self, resource_type: str) -> list[str]: ...

        def get_webhook_secret(self) -> str: ...

        def get_normalize_webhook_id(self, data: dict[str, Any]) -> str | None: ...

        def retrieve_webhooks(self) -> list[dict[str, Any]]: ...

        def _create_webhook_api(
            self,
            webhook_url: str,
            events: list[str],
            resource_type: list[str],
        ) -> str | None: ...

        def update_webhooks(
            self,
            resource_type: str,
            url: str,
            new_callback_url: str | None = None,
        ) -> bool: ...

        def delete_webhooks(self, resource_type: str, url: str) -> bool: ...

        def _detail_sending_postal(self, external_id: str, *, product: str) -> dict[str, Any]: ...

        def _detail_recipients_postal(
            self,
            external_id: str,
            *,
            product: str,
        ) -> list[dict[str, Any]]: ...

        def _serialize_recipient_ref(
            self,
            recipient: dict[str, Any],
            payload: dict[str, Any],
        ) -> dict[str, Any]: ...

        def _add_recipients_postal(
            self,
            recipients: list[dict[str, Any]],
            external_id: str,
            *,
            product: str,
        ) -> list[dict[str, Any]]: ...

        def _add_attachments_postal(
            self,
            attachments: list[dict[str, Any]],
            external_id: str,
            *,
            product: str,
        ) -> list[dict[str, Any]]: ...

        def _download_proof_bytes(self, url: str, *, product: str) -> bytes: ...

        def handle_webhook_registered_letter(
            self,
            payload: dict[str, Any] | bytes | bytearray,
        ) -> dict[str, Any]: ...

        def is_mode_sandbox(self) -> bool: ...

        def normalize_filename(self, name: str) -> str: ...

        def _is_send_disabled(self) -> bool: ...

        def _disabled_send_response(self, service_name: str, **extra: Any) -> dict[str, Any]: ...

else:

    class MailevaMixinTypingBase:
        """Runtime-empty counterpart of the static mixin contract."""
