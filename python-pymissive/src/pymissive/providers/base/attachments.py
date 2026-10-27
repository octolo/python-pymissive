from typing import Any


class AttachmentsMixin:
    """Mixin for attachments.

    ``attachments`` is set per instance by ``MissiveProviderBase.__init__``, not
    here: ``ProviderBase.__init__`` does not delegate to ``super()``, so a
    cooperative ``__init__`` on this mixin would never run.
    """

    attachments: list[Any]

    def get_attachments(self) -> list[Any]:
        """Get the attachments."""
        return self.attachments
