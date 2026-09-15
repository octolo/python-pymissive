"""Webhook secret generation (provider + date + extra)."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from pymissive.commands import webhook as webhook_cmd
from pymissive.webhook_secret import collect_mouse_entropy, generate_webhook_secret


def test_same_seed_is_stable():
    token = generate_webhook_secret("brevo", "extra", when=date(2026, 9, 14))
    again = generate_webhook_secret("brevo", "extra", when=date(2026, 9, 14))
    assert token == again
    assert token


def test_provider_is_case_insensitive():
    when = date(2026, 9, 14)
    assert generate_webhook_secret("Brevo", "x", when=when) == generate_webhook_secret(
        "brevo", "x", when=when
    )


def test_date_and_extra_change_the_token():
    a = generate_webhook_secret("brevo", "mouse-a", when=date(2026, 9, 14))
    b = generate_webhook_secret("brevo", "mouse-b", when=date(2026, 9, 14))
    c = generate_webhook_secret("brevo", "mouse-a", when=date(2026, 9, 15))
    assert len({a, b, c}) == 3


def test_naive_datetime_is_treated_as_utc():
    when = datetime(2026, 9, 14, 23, 0, 0)
    token = generate_webhook_secret("maileva", "k", when=when)
    assert token == generate_webhook_secret("maileva", "k", when=date(2026, 9, 14))


def test_aware_datetime_uses_utc_date():
    when = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)
    token = generate_webhook_secret("scaleway", "k", when=when)
    assert token == generate_webhook_secret("scaleway", "k", when=date(2026, 9, 15))


def test_missing_provider_or_extra_is_rejected():
    with pytest.raises(ValueError):
        generate_webhook_secret("", "extra")
    with pytest.raises(ValueError):
        generate_webhook_secret("brevo", "")
    with pytest.raises(ValueError):
        generate_webhook_secret("brevo", b"")


def test_collect_mouse_entropy_rejects_non_positive_seconds():
    with pytest.raises(ValueError):
        collect_mouse_entropy(0)


def test_cli_requires_provider(capsys):
    assert webhook_cmd._webhook_command(["secret"]) is False
    assert "--provider" in capsys.readouterr().err


def test_cli_secret_prints_the_token(capsys, monkeypatch):
    monkeypatch.setattr(
        webhook_cmd, "collect_mouse_entropy", lambda seconds: "mouse-samples"
    )
    assert webhook_cmd._webhook_command(["secret", "--provider", "brevo"]) is True
    out = capsys.readouterr().out
    expected = generate_webhook_secret("brevo", "mouse-samples")
    assert expected in out


def test_cli_unknown_subcommand(capsys):
    assert webhook_cmd._webhook_command(["nope", "--provider", "brevo"]) is False
    assert "secret" in capsys.readouterr().err


def test_cli_mouse_failure_is_an_error(capsys, monkeypatch):
    monkeypatch.setattr(
        webhook_cmd,
        "collect_mouse_entropy",
        MagicMock(side_effect=RuntimeError("No mouse movement captured")),
    )
    assert webhook_cmd._webhook_command(["secret", "--provider", "brevo"]) is False
    assert "No mouse movement" in capsys.readouterr().err


def test_cli_help_prints_the_doc(capsys):
    assert webhook_cmd._webhook_command(["--help"]) is True
    out = capsys.readouterr().out.lower()
    assert "webhook" in out
    assert "provider" in out
