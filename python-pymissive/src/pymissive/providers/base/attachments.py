class AttachmentsMixin:
    """Mixin for attachments."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.attachments = []

    def get_attachments(self):
        """Get the attachments."""
        return self.attachments
