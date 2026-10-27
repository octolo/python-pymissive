from typing import Any


class BrandedMixin:
    """Mixin for branded messages."""

    brands: list[str] = []

    def get_brands(self) -> list[str]:
        """Get the brands."""
        return self.brands

    def send_branded(self, brand_name: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Send a branded message."""
        if brand_name and hasattr(self, f"send_{brand_name}"):
            return getattr(self, f"send_{brand_name}")(**kwargs)
        raise NotImplementedError(f"send_{brand_name} method not implemented")
