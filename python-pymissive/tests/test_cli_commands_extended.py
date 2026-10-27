from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pymissive.commands import attachment, billing, help as command_help, missive, recipient, webhook


def provider_with(*services: str, normalized=None, response="provider response"):
    provider = SimpleNamespace()
    provider.call_service = Mock(return_value="result-id")
    provider.get_service_normalize = Mock(return_value=normalized if normalized is not None else [{"id": "one"}])
    provider.response = Mock(return_value=response)
    for service in services:
        setattr(provider, service, object())
    return provider


def install_provider(monkeypatch, module, provider, name="fake"):
    lookup = Mock(return_value=[provider])
    monkeypatch.setattr(module, "get_providers", lookup)
    return lookup


@pytest.mark.parametrize(
    ("module", "runner", "name"),
    [
        (missive, missive._missive_command, "missive"),
        (attachment, attachment._attachment_command, "attachment"),
        (billing, billing._billing_command, "billing"),
        (recipient, recipient._recipient_command, "recipient"),
        (webhook, webhook._webhook_command, "webhook"),
    ],
)
def test_command_help_is_delegated(monkeypatch, module, runner, name):
    printer = Mock(return_value=True)
    monkeypatch.setattr(command_help, "print_command_help", printer)

    assert runner(["--help"]) is True
    printer.assert_called_once_with(name)


def test_help_paths_prefer_packaged_files(monkeypatch, tmp_path):
    command_dir = tmp_path / "src" / "pymissive" / "commands"
    docs_dir = command_dir / "_docs"
    docs_dir.mkdir(parents=True)
    package_doc = docs_dir / "missive.md"
    package_doc.write_text("package docs", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("readme", encoding="utf-8")
    monkeypatch.setattr(command_help, "_get_commands_dir", lambda: command_dir)

    assert command_help.get_docs_path("missive") == package_doc
    assert command_help.get_readme_path() == readme


def test_help_paths_find_development_files(monkeypatch, tmp_path):
    command_dir = tmp_path / "src" / "pymissive" / "commands"
    command_dir.mkdir(parents=True)
    dev_doc = tmp_path / "src" / "docs" / "commands" / "billing.md"
    dev_doc.parent.mkdir(parents=True)
    dev_doc.write_text("development docs", encoding="utf-8")
    monkeypatch.setattr(command_help, "_get_commands_dir", lambda: command_dir)
    empty_cwd = tmp_path / "empty"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    assert command_help.get_docs_path("billing") == dev_doc
    assert command_help.get_docs_path("missing") == command_dir / "_docs" / "missing.md"
    assert command_help.get_readme_path() == command_dir.parent.parent / "README.md"


def test_print_command_help_success_and_missing(monkeypatch, tmp_path, capsys):
    path = tmp_path / "recipient.md"
    path.write_text("Recipient guide", encoding="utf-8")
    monkeypatch.setattr(command_help, "get_docs_path", lambda name: path)

    assert command_help.print_command_help("recipient") is True
    assert "Recipient guide" in capsys.readouterr().out

    path.unlink()
    assert command_help.print_command_help("recipient") is False
    assert "No documentation found" in capsys.readouterr().err


def test_print_command_help_reports_read_errors(monkeypatch, tmp_path, capsys):
    path = tmp_path / "docs"
    path.mkdir()
    monkeypatch.setattr(command_help, "get_docs_path", lambda name: path)

    assert command_help.print_command_help("recipient") is False
    assert "Cannot read doc" in capsys.readouterr().err


def test_print_readme_success_missing_and_read_error(monkeypatch, tmp_path, capsys):
    path = tmp_path / "README.md"
    path.write_text("Project readme", encoding="utf-8")
    monkeypatch.setattr(command_help, "get_readme_path", lambda: path)

    assert command_help.print_readme() is True
    assert "Project readme" in capsys.readouterr().out

    path.unlink()
    assert command_help.print_readme() is False

    path.mkdir()
    assert command_help.print_readme() is False


@pytest.mark.parametrize("module", [missive, attachment, billing])
def test_provider_lookup_accepts_config_and_reports_missing(monkeypatch, capsys, module):
    lookup = Mock(side_effect=[[], [object()]])
    monkeypatch.setattr(module, "get_providers", lookup)

    assert module._get_provider({"provider": "absent"}) is None
    assert "not found" in capsys.readouterr().err
    assert module._get_provider({"filter": "fake", "dir": "/providers", "json": "/providers.json"})[0] == "fake"
    lookup.assert_called_with(
        lib_name="pymissive",
        attribute_search={"name": "fake"},
        dir_path="/providers",
        json="/providers.json",
    )


def test_missive_send_builds_payload_and_prints_response(monkeypatch, capsys):
    provider = provider_with("send_email", response="sent: 42")
    install_provider(monkeypatch, missive, provider)

    assert missive._missive_command(
        [
            "send",
            "--provider",
            "fake",
            "--missive-type",
            "email",
            "--recipient-email",
            "user@example.test",
            "--recipient-name",
            "Ada",
            "--sender-email",
            "sender@example.test",
            "--sender-name",
            "Grace",
            "--sender-phone",
            "+33123456789",
            "--sender-address",
            '{"city":"Paris"}',
            "--subject",
            "Hello",
            "--body",
            "Plain text",
        ]
    )

    provider.call_service.assert_called_once_with(
        "send_email",
        subject="Hello",
        body_text="Plain text",
        recipients=[{"email": "user@example.test", "name": "Ada"}],
        sender={
            "email": "sender@example.test",
            "name": "Grace",
            "phone": "+33123456789",
            "address": {"city": "Paris"},
        },
        sender_email="sender@example.test",
        sender_name="Grace",
    )
    provider.response.assert_called_once_with("send_email", False, output_format="terminal")
    assert "sent: 42" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("recipient_args", "expected"),
    [
        (["--recipient-phone", "+33123456789"], [{"phone": "+33123456789", "name": ""}]),
        (["--recipient-address", '{"city":"Paris"}'], [{"address": {"city": "Paris"}, "name": ""}]),
        (["--recipients", '[{"email":"one@example.test"}]'], [{"email": "one@example.test"}]),
    ],
)
def test_missive_send_accepts_each_recipient_form(monkeypatch, recipient_args, expected):
    provider = provider_with("send_sms")
    install_provider(monkeypatch, missive, provider)

    assert missive._missive_command(["send", "--provider", "fake", "--type", "sms", *recipient_args])
    assert provider.call_service.call_args.kwargs["recipients"] == expected


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["unknown"], "Use create"),
        (["send", "--provider", "fake"], "--missive-type required"),
        (
            ["send", "--provider", "fake", "--type", "email", "--recipients", "{}"],
            "must be a JSON array",
        ),
        (
            ["send", "--provider", "fake", "--type", "email", "--recipients", "{"],
            "Invalid JSON",
        ),
        (["create", "missive", "--provider", "fake", "--type", "email"], "Unknown resource"),
        (["create", "--provider", "fake"], "--type required"),
        (["update", "missive", "--provider", "fake", "--type", "email"], "Unknown resource"),
        (["update", "--provider", "fake", "--type", "email"], "--webhook-id and --type"),
        (["delete", "missive", "--provider", "fake"], "--external-id"),
        (["delete", "webhook", "--provider", "fake", "--type", "email"], "--webhook-id and --type"),
        (["delete", "other", "--provider", "fake"], "Unknown resource"),
        (["retrieve", "other", "--provider", "fake"], "Use webhooks"),
        (["retrieve", "events", "--provider", "fake"], "--type required"),
        (
            ["retrieve", "events", "--provider", "fake", "--type", "email"],
            "--start-date and --end-date",
        ),
        (["retrieve", "tracking_number", "--provider", "fake"], "--type required"),
        (
            ["retrieve", "tracking_number", "--provider", "fake", "--type", "registered_letter"],
            "--external-id",
        ),
        (["cancel", "--provider", "fake"], "--external-id"),
    ],
)
def test_missive_validations(monkeypatch, capsys, argv, message):
    install_provider(monkeypatch, missive, provider_with())

    assert missive._missive_command(argv) is False
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "service", "kwargs", "output"),
    [
        (
            ["create", "webhook", "--provider", "fake", "--type", "email", "--scheme", "http", "--domain", "host/"],
            "create_webhook_email",
            {"webhook_data": {"id": "", "type": "email", "url": "http://host/webhook/fake/email/"}},
            "webhook_id=result-id",
        ),
        (
            ["update", "webhook", "--provider", "fake", "--type", "sms", "--webhook-id", "wh-1"],
            "update_webhook_sms",
            {
                "webhook_data": {
                    "id": "wh-1",
                    "type": "sms",
                    "url": "https://localhost:8080/webhook/fake/sms/",
                }
            },
            "Webhook updated.",
        ),
        (
            ["delete", "webhook", "--provider", "fake", "--type", "email", "--webhook-id", "wh-1"],
            "delete_webhook_email",
            {"webhook_data": {"id": "wh-1", "type": "email"}},
            "Webhook deleted.",
        ),
        (
            ["delete", "missive", "--provider", "fake", "--external-id", "ext-1"],
            "delete_registered_letter",
            {"external_id": "ext-1"},
            "deleted registered_letter sending",
        ),
        (
            ["cancel", "--provider", "fake", "--external-id", "ext-1"],
            "cancel_registered_letter",
            {"external_id": "ext-1"},
            "cancelled registered_letter",
        ),
    ],
)
def test_missive_mutating_subcommands(monkeypatch, capsys, argv, service, kwargs, output):
    provider = provider_with(service)
    install_provider(monkeypatch, missive, provider)

    assert missive._missive_command(argv)
    provider.call_service.assert_called_once_with(service, **kwargs)
    assert output in capsys.readouterr().out


@pytest.mark.parametrize(
    ("resource", "service"),
    [
        ("webhooks", "retrieve_webhooks"),
        ("email", "retrieve_email"),
        ("sms", "retrieve_sms"),
        ("registered_letter", "retrieve_registered_letter"),
        ("letter", "retrieve_letter"),
    ],
)
def test_missive_retrieve_simple_resources(monkeypatch, capsys, resource, service):
    provider = provider_with(service, normalized=[{"resource": resource}])
    install_provider(monkeypatch, missive, provider)

    assert missive._missive_command(["retrieve", resource, "--provider", "fake"])
    provider.call_service.assert_called_once_with(service)
    provider.get_service_normalize.assert_called_once_with(service)
    assert resource in capsys.readouterr().out


@pytest.mark.parametrize(
    ("resource", "missive_type", "service", "extra_args", "kwargs"),
    [
        (
            "events",
            "email",
            "retrieve_events_email",
            ["--start-date", "2026-01-01", "--end-date", "2026-01-31"],
            {"start_date": "2026-01-01", "end_date": "2026-01-31"},
        ),
        (
            "billings",
            "registered_letter",
            "retrieve_billings_registered_letter",
            ["--start-date", "2026-01-01", "--end-date", "2026-01-31"],
            {"start_date": "2026-01-01", "end_date": "2026-01-31"},
        ),
        (
            "tracking_number",
            "registered_letter",
            "tracking_number_registered_letter",
            ["--external-id", "ext-1"],
            {"external_id": "ext-1"},
        ),
    ],
)
def test_missive_retrieve_typed_resources(monkeypatch, resource, missive_type, service, extra_args, kwargs):
    provider = provider_with(service)
    install_provider(monkeypatch, missive, provider)

    assert missive._missive_command(["retrieve", resource, "--provider", "fake", "--type", missive_type, *extra_args])
    provider.call_service.assert_called_once_with(service, **kwargs)


@pytest.mark.parametrize(
    "argv",
    [
        ["send", "--provider", "fake", "--type", "email", "--recipient-email", "user@example.test"],
        ["create", "--provider", "fake", "--type", "email"],
        ["retrieve", "email", "--provider", "fake"],
        ["update", "--provider", "fake", "--type", "email", "--webhook-id", "wh-1"],
        ["delete", "webhook", "--provider", "fake", "--type", "email", "--webhook-id", "wh-1"],
        ["cancel", "--provider", "fake", "--external-id", "ext-1"],
    ],
)
def test_missive_reports_unsupported_services(monkeypatch, capsys, argv):
    install_provider(monkeypatch, missive, provider_with())

    assert missive._missive_command(argv) is False
    assert "does not support" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["send", "--provider", "fake", "--type", "email", "--recipient-email", "user@example.test"],
        ["delete", "missive", "--provider", "fake", "--external-id", "ext-1"],
        ["cancel", "--provider", "fake", "--external-id", "ext-1"],
    ],
)
def test_missive_provider_exceptions_are_reported(monkeypatch, capsys, argv):
    services = ("send_email", "delete_registered_letter", "cancel_registered_letter")
    provider = provider_with(*services)
    provider.call_service.side_effect = RuntimeError("provider unavailable")
    install_provider(monkeypatch, missive, provider)

    assert missive._missive_command(argv) is False
    assert "provider unavailable" in capsys.readouterr().err


def test_attachment_retrieve_generic_service(monkeypatch, capsys):
    provider = provider_with("retrieve_attachments", normalized=[{"name": "invoice.pdf"}])
    install_provider(monkeypatch, attachment, provider)

    assert attachment._attachment_command(["retrieve", "--provider", "fake"])
    provider.call_service.assert_called_once_with("retrieve_attachments")
    assert "invoice.pdf" in capsys.readouterr().out


def test_attachment_retrieve_postal_fallback(monkeypatch, capsys):
    provider = SimpleNamespace(get_attachments_registered_letter=Mock(return_value=[{"name": "proof.pdf"}]))
    install_provider(monkeypatch, attachment, provider)

    assert attachment._attachment_command(["retrieve", "--provider", "fake", "--external-id", "ext-1"])
    provider.get_attachments_registered_letter.assert_called_once_with(external_id="ext-1")
    assert "proof.pdf" in capsys.readouterr().out


def test_attachment_delete_success(monkeypatch, capsys):
    provider = SimpleNamespace(delete_attachment_registered_letter=Mock())
    install_provider(monkeypatch, attachment, provider)

    assert attachment._attachment_command(
        [
            "delete",
            "--provider",
            "fake",
            "--external-id",
            "ext-1",
            "--document-id",
            "doc-1",
        ]
    )
    provider.delete_attachment_registered_letter.assert_called_once_with(external_id="ext-1", document_id="doc-1")
    assert "Attachment deleted." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("provider", "argv", "message"),
    [
        (SimpleNamespace(), ["retrieve", "--provider", "fake"], "does not support"),
        (
            SimpleNamespace(get_attachments_registered_letter=Mock()),
            ["retrieve", "--provider", "fake"],
            "--external-id",
        ),
        (
            SimpleNamespace(),
            ["delete", "--provider", "fake", "--external-id", "ext-1", "--document-id", "doc-1"],
            "does not support",
        ),
        (
            SimpleNamespace(delete_attachment_registered_letter=Mock()),
            ["delete", "--provider", "fake"],
            "--external-id and --document-id",
        ),
        (SimpleNamespace(), ["unknown", "--provider", "fake"], "Unknown subcommand"),
    ],
)
def test_attachment_validations(monkeypatch, capsys, provider, argv, message):
    install_provider(monkeypatch, attachment, provider)

    assert attachment._attachment_command(argv) is False
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "--recipients required"),
        ("{", "Invalid JSON"),
        ('{"email":"user@example.test"}', "JSON array"),
    ],
)
def test_recipient_parse_errors(capsys, raw, message):
    assert recipient._recipient_command(["validate", "--recipients", raw]) is False
    assert message in capsys.readouterr().err


def test_recipient_validate_filters_invalid_entries(capsys):
    raw = '[{"email":"one@example.test"},{"phone":"+331"},42,{"name":"Missing"}]'

    assert recipient._recipient_command(["validate", "--recipients", raw])
    captured = capsys.readouterr()
    assert '"email": "one@example.test"' in captured.out
    assert '"phone": "+331"' in captured.out
    assert "must be object" in captured.err
    assert "missing email/phone/address" in captured.err


def test_recipient_format_preserves_entries(capsys):
    assert recipient._recipient_command(["format", "--recipients", '[{"address":{"city":"Paris"}}]'])
    assert '"city": "Paris"' in capsys.readouterr().out


def test_recipient_rejects_unknown_subcommand(capsys):
    assert recipient._recipient_command(["unknown", "--recipients", '[{"email":"one@example.test"}]']) is False
    assert "Unknown subcommand" in capsys.readouterr().err


def test_billing_retrieve_single_typed_service(monkeypatch, capsys):
    provider = provider_with("get_billings_registered_letter", normalized={"amount": 12})
    install_provider(monkeypatch, billing, provider)

    assert billing._billing_command(["retrieve", "--provider", "fake", "--external-id", "ext-1"])
    provider.call_service.assert_called_once_with("get_billings_registered_letter", external_id="ext-1")
    assert '"amount": 12' in capsys.readouterr().out


def test_billing_retrieve_single_without_external_id(monkeypatch):
    provider = provider_with("get_billings_email")
    install_provider(monkeypatch, billing, provider)

    assert billing._billing_command(["retrieve", "--provider", "fake", "--type", "email"])
    provider.call_service.assert_called_once_with("get_billings_email")


def test_billing_retrieve_legacy_fallback(monkeypatch):
    provider = provider_with("retrieve_billing")
    install_provider(monkeypatch, billing, provider)

    assert billing._billing_command(["retrieve", "--provider", "fake"])
    provider.call_service.assert_called_once_with("retrieve_billing")


def test_billing_retrieve_bulk(monkeypatch):
    provider = provider_with("retrieve_billings_email")
    install_provider(monkeypatch, billing, provider)

    assert billing._billing_command(
        [
            "retrieve",
            "--provider",
            "fake",
            "--type",
            "email",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-01-31",
        ]
    )
    provider.call_service.assert_called_once_with(
        "retrieve_billings_email",
        start_date="2026-01-01",
        end_date="2026-01-31",
    )


@pytest.mark.parametrize(
    ("argv", "provider", "message"),
    [
        (["unknown", "--provider", "fake"], provider_with(), "Unknown subcommand"),
        (
            ["retrieve", "--provider", "fake", "--start-date", "2026-01-01"],
            provider_with(),
            "--start-date and --end-date",
        ),
        (
            [
                "retrieve",
                "--provider",
                "fake",
                "--type",
                "email",
                "--start-date",
                "2026-01-01",
                "--end-date",
                "2026-01-31",
            ],
            provider_with(),
            "does not support",
        ),
        (["retrieve", "--provider", "fake"], provider_with(), "does not support"),
    ],
)
def test_billing_validations(monkeypatch, capsys, argv, provider, message):
    install_provider(monkeypatch, billing, provider)

    assert billing._billing_command(argv) is False
    assert message in capsys.readouterr().err


def test_billing_options_default_to_registered_letter():
    assert billing._billing_options({"args": ["retrieve"]}) == ("retrieve", "registered_letter", False)
    assert billing._billing_options({"start_date": "2026-01-01"}) == ("retrieve", "registered_letter", True)


@pytest.mark.parametrize("missive_type", ["unknown", ""])
def test_billing_service_name_reports_invalid_types(capsys, missive_type):
    assert billing._service_name("get_billings", missive_type) == ""
    assert "Unknown missive type" in capsys.readouterr().err


def test_webhook_secret_success(monkeypatch, capsys):
    entropy = Mock(return_value=b"entropy")
    generator = Mock(return_value="secret-token")
    monkeypatch.setattr(webhook, "collect_mouse_entropy", entropy)
    monkeypatch.setattr(webhook, "generate_webhook_secret", generator)

    assert webhook._webhook_command(["secret", "--provider", "brevo", "--seconds", "0.5"])
    entropy.assert_called_once_with(0.5)
    generator.assert_called_once_with("brevo", b"entropy")
    captured = capsys.readouterr()
    assert "secret-token" in captured.out
    assert "Move the mouse for 0.5s" in captured.err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["unknown", "--provider", "brevo"], "Unknown subcommand"),
        (["secret"], "--provider required"),
    ],
)
def test_webhook_validations(capsys, argv, message):
    assert webhook._webhook_command(argv) is False
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("exception", [ValueError("bad provider"), RuntimeError("no display")])
def test_webhook_entropy_errors(monkeypatch, capsys, exception):
    monkeypatch.setattr(webhook, "collect_mouse_entropy", Mock(side_effect=exception))

    assert webhook._webhook_command(["secret", "--provider", "brevo"]) is False
    assert str(exception) in capsys.readouterr().err
