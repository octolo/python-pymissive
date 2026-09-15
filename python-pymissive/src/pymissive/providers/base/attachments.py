class AttachmentsMixin:
    """Mixin for attachments.

    ``attachments`` is set per instance by ``MissiveProviderBase.__init__``, not
    here: ``ProviderBase.__init__`` does not delegate to ``super()``, so a
    cooperative ``__init__`` on this mixin would never run.
    """

    def get_attachments(self):
        """Get the attachments."""
        return self.attachments
