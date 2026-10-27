"""Postal tracking and webhook-secret behaviour at external boundaries."""

import builtins
import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from pymissive import postal_tracking
from pymissive import webhook_secret


def test_postal_tracking_data_loads_from_packaged_resource_and_is_cached():
    postal_tracking.postal_tracking_urls.cache_clear()

    first = postal_tracking.postal_tracking_urls()
    second = postal_tracking.postal_tracking_urls()

    assert first is second
    assert first["FR"]["carrier"] == "La Poste"
    assert first["US"]["name"] == "USPS"


def test_tracking_url_normalizes_country_and_quotes_the_identifier():
    assert postal_tracking.get_tracking_url(" fr ", "AB 12/é") == (
        "https://www.laposte.fr/outils/suivre-vos-envois?code=AB%2012%2F%C3%A9"
    )


@pytest.mark.parametrize("country_code", [None, "", "  ", "XX"])
def test_tracking_url_returns_none_for_missing_or_unknown_country(country_code):
    assert postal_tracking.get_tracking_url(country_code, "ABC") is None


def test_tracking_url_requires_number_only_when_carrier_template_does(monkeypatch):
    monkeypatch.setattr(
        postal_tracking,
        "postal_tracking_urls",
        lambda: {
            "FR": {"tracking_url": "https://carrier.test/{tracking}"},
            "BG": {"tracking_url": "https://carrier.test/track"},
            "ZZ": {"name": "No URL"},
        },
    )

    assert postal_tracking.get_tracking_url("FR") is None
    assert postal_tracking.get_tracking_url("FR", 0) is None
    assert postal_tracking.get_tracking_url("BG") == "https://carrier.test/track"
    assert postal_tracking.get_tracking_url("ZZ", "123") is None


def test_webhook_secret_matches_documented_sha256_construction():
    expected = hashlib.sha256(b"brevo\n2026-09-14\nbinary\x00entropy").digest()
    token = webhook_secret.generate_webhook_secret(
        "  Brevo  ",
        b"binary\x00entropy",
        when=date(2026, 9, 14),
    )

    import base64

    assert token == base64.urlsafe_b64encode(expected).decode("ascii").rstrip("=")
    assert "=" not in token
    assert len(token) == 43


def test_string_and_utf8_bytes_entropy_are_equivalent():
    when = date(2026, 9, 14)

    assert webhook_secret.generate_webhook_secret("provider", "café", when=when) == (
        webhook_secret.generate_webhook_secret("provider", "café".encode(), when=when)
    )


def test_aware_datetime_is_converted_to_utc_before_selecting_day():
    local_zone = timezone(timedelta(hours=2))
    local_time = datetime(2026, 9, 15, 1, 30, tzinfo=local_zone)

    assert webhook_secret.generate_webhook_secret("provider", "x", when=local_time) == (
        webhook_secret.generate_webhook_secret("provider", "x", when=date(2026, 9, 14))
    )


def test_default_secret_date_comes_from_current_utc_day(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, _tz=None):
            return cls(2026, 9, 14, 23, 59, tzinfo=timezone.utc)

    monkeypatch.setattr(webhook_secret, "datetime", FrozenDateTime)

    assert webhook_secret.generate_webhook_secret("provider", "x") == (
        webhook_secret.generate_webhook_secret("provider", "x", when=date(2026, 9, 14))
    )


def test_collect_mouse_entropy_reports_missing_tkinter(monkeypatch):
    real_import = builtins.__import__

    def import_without_tkinter(name, *args, **kwargs):
        if name == "tkinter":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "tkinter", raising=False)
    monkeypatch.setattr(builtins, "__import__", import_without_tkinter)

    with pytest.raises(RuntimeError, match="tkinter is required"):
        webhook_secret.collect_mouse_entropy(0.1)


class _FakeLabel:
    def __init__(self, root, **kwargs):
        root.label = self
        self.text = kwargs["text"]

    def pack(self, **kwargs):
        self.pack_options = kwargs

    def config(self, *, text):
        self.text = text


class _FakeRoot:
    def __init__(self, *, move_mouse):
        self.move_mouse = move_mouse
        self.callback = None
        self.motion_handler = None
        self.destroyed = False

    def title(self, value):
        self.window_title = value

    def geometry(self, value):
        self.window_geometry = value

    def bind(self, event, callback):
        assert event == "<Motion>"
        self.motion_handler = callback

    def after(self, milliseconds, callback):
        assert milliseconds == 100
        self.callback = callback

    def mainloop(self):
        if self.move_mouse:
            self.motion_handler(SimpleNamespace(x_root=12, y_root=34))
        self.callback()

    def destroy(self):
        self.destroyed = True


def _fake_tkinter(move_mouse):
    root = _FakeRoot(move_mouse=move_mouse)
    return SimpleNamespace(Tk=lambda: root, Label=_FakeLabel), root


def test_collect_mouse_entropy_samples_motion_and_closes_window(monkeypatch):
    tkinter, root = _fake_tkinter(move_mouse=True)
    monotonic_values = iter([10.0, 11.1])
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setattr(webhook_secret.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(webhook_secret.time, "monotonic_ns", lambda: 123456)

    result = webhook_secret.collect_mouse_entropy(1)

    assert result == "12,34,123456"
    assert root.destroyed is True
    assert root.window_title == "pymissive — move the mouse"
    assert root.window_geometry == "480x160"


def test_collect_mouse_entropy_rejects_session_without_motion(monkeypatch):
    tkinter, root = _fake_tkinter(move_mouse=False)
    monotonic_values = iter([10.0, 11.1])
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setattr(webhook_secret.time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(RuntimeError, match="No mouse movement captured"):
        webhook_secret.collect_mouse_entropy(1)

    assert root.destroyed is True


def test_collect_mouse_entropy_updates_count_while_waiting(monkeypatch):
    tkinter, root = _fake_tkinter(move_mouse=True)
    monotonic_values = iter([10.0, 10.5, 11.1])
    original_after = root.after

    def run_until_destroyed(milliseconds, callback):
        original_after(milliseconds, callback)
        if root.callback is callback and root.motion_handler is not None:
            root.callback = lambda: (callback(), callback())

    root.after = run_until_destroyed
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setattr(webhook_secret.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(webhook_secret.time, "monotonic_ns", lambda: 1)

    assert webhook_secret.collect_mouse_entropy(1) == "12,34,1"
    assert "1 samples" in root.label.text
