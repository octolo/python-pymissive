class BrandedMixin:
    """Mixin for branded messages."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.brands = []

    def get_brands(self):
        """Get the brands."""
        return self.brands

    def send_branded(self, brand_name: str, **kwargs):
        """Send a branded message."""
        if hasattr(self, f"send_{brand_name}"):
            return getattr(self, f"send_{brand_name}")(**kwargs)
        raise NotImplementedError(f"send_{brand_name} method not implemented")