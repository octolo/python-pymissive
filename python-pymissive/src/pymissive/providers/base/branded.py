class BrandedMixin:
    """Mixin for branded messages."""

    brands: list[str] = []

    def get_brands(self):
        """Get the brands."""
        return self.brands

    def send_branded(self, brand_name: str, **kwargs):
        """Send a branded message."""
        if hasattr(self, f"send_{brand_name}"):
            return getattr(self, f"send_{brand_name}")(**kwargs)
        raise NotImplementedError(f"send_{brand_name} method not implemented")
