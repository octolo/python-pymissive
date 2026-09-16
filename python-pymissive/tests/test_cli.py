"""CLI help and the subcommand argv that clicommands actually returns."""

from __future__ import annotations

from pymissive.cli import main
from pymissive.commands import attachment, billing, missive, recipient


def test_main_help_prints_the_readme(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "pymissive" in out.lower() or "missive" in out.lower()


def test_missive_without_provider_explains_the_flag(capsys):
    assert missive._missive_command(["send", "--missive-type", "email"]) is False
    assert "--provider" in capsys.readouterr().err


def test_missive_send_without_type_is_rejected(capsys):
    # parse_args still runs; provider lookup happens first.
    assert missive._missive_command(["send", "--provider", "missing-provider"]) is False
    err = capsys.readouterr().err
    assert "Provider" in err or "missive-type" in err


def test_attachment_add_is_reached_from_args(capsys, monkeypatch):
    """Regression: ``parsed.get('command')`` is always {} — subcommands live in ``args``."""
    monkeypatch.setattr(attachment, "get_providers", lambda **kwargs: [object()])
    assert attachment._attachment_command(["add", "--provider", "maileva"]) is False
    assert "not yet implemented" in capsys.readouterr().err


def test_recipient_validate_requires_recipients(capsys):
    assert recipient._recipient_command(["validate"]) is False
    assert "--recipients" in capsys.readouterr().err


def test_billing_without_provider_explains_the_flag(capsys):
    assert billing._billing_command(["retrieve"]) is False
    assert "--provider" in capsys.readouterr().err


def test_billing_rejects_an_unknown_type(capsys, monkeypatch):
    monkeypatch.setattr(billing, "get_providers", lambda **kwargs: [object()])
    assert (
        billing._billing_command(
            ["retrieve", "--provider", "maileva", "--type", "lre", "--external-id", "1"]
        )
        is False
    )
    assert "Unknown missive type" in capsys.readouterr().err
