"""Framework-agnostic helpers."""

from pymissive.utils import HTTP_DOCUMENT_TIMEOUT, HTTP_TIMEOUT, is_disable_send


def test_http_timeouts_leave_room_for_document_transfers():
    assert HTTP_TIMEOUT == 30
    assert HTTP_DOCUMENT_TIMEOUT == 120
    assert HTTP_DOCUMENT_TIMEOUT > HTTP_TIMEOUT


def test_is_disable_send_reads_the_environment(monkeypatch):
    monkeypatch.delenv("PYMISSIVE_DISABLE_SEND", raising=False)
    assert is_disable_send() is False
    monkeypatch.setenv("PYMISSIVE_DISABLE_SEND", "true")
    assert is_disable_send() is True
    monkeypatch.setenv("PYMISSIVE_DISABLE_SEND", "0")
    assert is_disable_send() is False
