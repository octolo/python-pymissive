"""Generate an opt-in webhook secret from provider name, date, and extra entropy."""

from __future__ import annotations

import base64
import hashlib
import time
from datetime import date, datetime, timezone


def generate_webhook_secret(
    provider: str,
    extra: str | bytes,
    *,
    when: date | datetime | None = None,
) -> str:
    """Return a url-safe secret seeded by provider, UTC date, and ``extra``.

    ``extra`` is mouse-motion samples on the CLI, or Django ``SECRET_KEY``
    in the admin. The same inputs always produce the same token.
    """
    name = (provider or "").strip().lower()
    if not name:
        raise ValueError("provider is required")
    extra_bytes = extra.encode("utf-8") if isinstance(extra, str) else extra
    if not extra_bytes:
        raise ValueError("extra entropy is required")
    day = _as_utc_date(when)
    material = f"{name}\n{day.isoformat()}\n".encode("utf-8") + extra_bytes
    digest = hashlib.sha256(material).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def collect_mouse_entropy(seconds: float = 5) -> str:
    """Sample pointer positions for ``seconds``. Needs a display (tkinter)."""
    if seconds <= 0:
        raise ValueError("seconds must be greater than 0")
    try:
        import tkinter as tk
    except ImportError as exc:
        raise RuntimeError(
            "tkinter is required to collect mouse entropy"
        ) from exc

    samples: list[str] = []
    root = tk.Tk()
    root.title("pymissive — move the mouse")
    root.geometry("480x160")
    label = tk.Label(
        root,
        text=f"Move the mouse for {seconds:.0f}s…",
        font=("sans-serif", 14),
    )
    label.pack(expand=True, fill="both", padx=16, pady=16)

    deadline = time.monotonic() + seconds

    def on_motion(event):
        samples.append(f"{event.x_root},{event.y_root},{time.monotonic_ns()}")

    root.bind("<Motion>", on_motion)

    def tick():
        left = deadline - time.monotonic()
        if left <= 0:
            root.destroy()
            return
        label.config(
            text=f"Move the mouse for {left:.1f}s… ({len(samples)} samples)"
        )
        root.after(100, tick)

    root.after(100, tick)
    root.mainloop()
    if not samples:
        raise RuntimeError("No mouse movement captured")
    return "|".join(samples)


def _as_utc_date(when: date | datetime | None) -> date:
    if when is None:
        return datetime.now(timezone.utc).date()
    if isinstance(when, datetime):
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.astimezone(timezone.utc).date()
    return when
