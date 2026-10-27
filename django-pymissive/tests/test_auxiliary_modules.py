from __future__ import annotations

import importlib
import sys
from datetime import date, datetime
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.core.management import call_command

from django_pymissive import pdf
from django_pymissive.management.commands import sync_billings
from django_pymissive.management.commands import update_translation_catalog


def test_sync_billings_rejects_invalid_date():
    stderr = StringIO()

    call_command("sync_billings", date="23/10/2026", stderr=stderr)

    assert "Invalid date format" in stderr.getvalue()


def test_sync_billings_processes_skips_and_reports_errors():
    synced = MagicMock(id="synced")
    synced.can_billings.return_value = True
    skipped = MagicMock(id="skipped")
    skipped.can_billings.return_value = False
    failed = MagicMock(id="failed")
    failed.can_billings.return_value = True
    failed.get_billings.side_effect = RuntimeError("provider unavailable")

    queryset = MagicMock()
    queryset.count.return_value = 3
    queryset.__iter__.return_value = iter([synced, skipped, failed])
    manager = MagicMock()
    manager.filter.return_value.filter.return_value.exclude.return_value.order_by.return_value = queryset
    fake_model = SimpleNamespace(objects=manager)
    command = sync_billings.Command()
    command.stdout = StringIO()
    command.stderr = StringIO()

    with patch.object(sync_billings, "Missive", fake_model):
        command.handle(date="2026-10-01", verbosity=2)

    synced.to_missivebilling.all.return_value.delete.assert_called_once_with()
    synced.get_billings.assert_called_once_with()
    skipped.get_billings.assert_not_called()
    assert "1 synced, 1 skipped, 1 errors" in command.stdout.getvalue()
    assert "provider unavailable" in command.stderr.getvalue()


def test_translation_catalog_generation_and_command(tmp_path):
    strings = update_translation_catalog.extract_strings_from_config()
    content = update_translation_catalog.generate_catalog_content({'A "quote"', r"A\path", ""})

    assert "Email" in strings
    assert '_("")' not in content
    assert r"A \"quote\"" in content
    assert r"A\\path" in content

    resolved = MagicMock()
    first_parent = MagicMock()
    second_parent = MagicMock()
    resolved.parent = first_parent
    first_parent.parent = second_parent
    second_parent.parent = tmp_path
    source_path = MagicMock()
    source_path.resolve.return_value = resolved
    command = update_translation_catalog.Command()
    command.stdout = StringIO()

    with (
        patch.object(update_translation_catalog, "Path", return_value=source_path),
        patch.object(update_translation_catalog, "extract_strings_from_config", return_value={"Email"}),
    ):
        command.handle()

    generated = (tmp_path / "translation_catalog.py").read_text()
    assert '_("Email")' in generated
    assert "1 translatable strings" in command.stdout.getvalue()


def test_generated_translation_catalog_is_importable():
    module = importlib.import_module("django_pymissive.translation_catalog")
    importlib.reload(module)


def test_pdf_generator_compiles_html_and_extra_css(monkeypatch):
    rendered = {}

    class HTML:
        def __init__(self, *, string):
            rendered["html"] = string

        def write_pdf(self):
            return b"%PDF-fake"

    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=HTML))
    missive = MagicMock(missive_type="email")
    missive.missive_context.return_value = {"name": "Ada"}
    missive.get_locally_or_campaign_value.side_effect = [None, "Hello {{ name }}"]

    result = pdf.body_to_pdf(missive, extra_css=".message { color: red; }")

    assert result == b"%PDF-fake"
    assert "Hello Ada" in rendered["html"]
    assert ".message { color: red; }" in rendered["html"]


def test_pdf_generator_uses_postal_layout_and_css(monkeypatch, tmp_path):
    css = tmp_path / "letter_page.css"
    css.write_text(".a4-page { width: 210mm; }")
    monkeypatch.setattr(pdf.finders, "find", lambda _path: str(css))
    postal_html = Mock(return_value="<main>Letter</main>")
    monkeypatch.setattr(pdf, "_postal_letter_html", postal_html)

    class HTML:
        def __init__(self, *, string):
            self.string = string

        def write_pdf(self):
            assert "width: 210mm" in self.string
            return b"%PDF-postal"

    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=HTML))
    missive = MagicMock(missive_type="registered_letter")

    assert pdf.body_to_pdf(missive, postal_recipient_pk="invalid") == b"%PDF-postal"
    postal_html.assert_called_once_with(missive, postal_recipient_pk=None)


class _FakeTask:
    def __init__(self, func):
        self.func = func
        self.delay = Mock()

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)


def _load_optional_task_module(monkeypatch, module_name, dependency_name, dependency):
    monkeypatch.setitem(sys.modules, dependency_name, dependency)
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    monkeypatch.setitem(sys.modules, module_name, module)
    return module


def test_celery_backend_dispatches_and_serializes_arguments(monkeypatch):
    celery = SimpleNamespace(shared_task=lambda func: _FakeTask(func))
    module = _load_optional_task_module(
        monkeypatch,
        "django_pymissive.task.celery",
        "celery",
        celery,
    )
    run_campaign = Mock()
    imported = Mock()
    monkeypatch.setattr(module, "run_campaign", run_campaign)
    monkeypatch.setattr(module, "import_string", Mock(return_value=imported))

    module.celery_campaign_task("campaign")
    module.celery_enqueue_task("app.tasks.send", ["arg"], {"key": "value"})
    backend = module.CeleryBackend()
    backend.delay("campaign")

    def target():
        return None

    backend.enqueue(target, date(2026, 10, 23), sent_at=datetime(2026, 10, 23, 12, 0))

    run_campaign.assert_called_once_with("campaign")
    imported.assert_called_once_with("arg", key="value")
    module.celery_campaign_task.delay.assert_called_once_with("campaign")
    module.celery_enqueue_task.delay.assert_called_once_with(
        f"{target.__module__}.{target.__name__}",
        ["2026-10-23"],
        {"sent_at": "2026-10-23T12:00:00"},
    )


def test_rq_backend_dispatches_to_default_queue(monkeypatch):
    queue = Mock()
    django_rq = SimpleNamespace(get_queue=Mock(return_value=queue))
    module = _load_optional_task_module(
        monkeypatch,
        "django_pymissive.task.django_rq",
        "django_rq",
        django_rq,
    )
    backend = module.RQBackend()
    target = Mock()

    backend.enqueue(target, "arg", key="value")
    with patch.object(backend, "enqueue") as enqueue:
        backend.delay("campaign")

    django_rq.get_queue.assert_called_once_with("default")
    queue.enqueue.assert_called_once_with(target, "arg", key="value")
    enqueue.assert_called_once_with(module.run_campaign, "campaign")
