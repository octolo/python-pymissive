"""Integration tests for ``Missive`` / ``MissiveCampaign`` processor hooks.

Covers the "most specific wins" resolver semantics on the live models
(``get_body_processors`` / ``get_first_document_processors`` /
``get_attachment_processors``) and the actual ``body_to_pdf`` chain
invocation. Uses an in-memory SQLite DB via pytest-django.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.campaign_step import CampaignStep
from django_pymissive.models.missive import Missive
from django_pymissive.processors.pdf import MissivePdfProcessor

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Module-level capture state — referenced by dotted-path inside tests.
# ---------------------------------------------------------------------------

_renderer_calls: list[dict] = []


def _captured_renderer(missive, pdf_bytes, *, campaign=None, context=None, **kwargs):
    """Test renderer that records its call args and returns sentinel bytes."""
    _renderer_calls.append(
        {
            "missive": missive,
            "pdf_bytes_in": pdf_bytes,
            "campaign": campaign,
            "context": dict(context or {}),
            "kwargs": kwargs,
        }
    )
    return b"%PDF-FAKE"


class _CapturingProcessor(MissivePdfProcessor):
    """Class-based processor used to verify per-entry kwargs reach ``process``."""

    def process(self, missive, pdf_bytes, *, campaign=None, context=None, sentinel="?", **kwargs):
        return f"%PDF-CLS-{sentinel}".encode()


def _make_campaign(**overrides) -> MissiveCampaign:
    defaults = {"subject": "Campaign-A"}
    defaults.update(overrides)
    return MissiveCampaign.objects.create(**defaults)


def _make_missive(*, campaign=None, missive_type="email", **overrides) -> Missive:
    campaign_step = None
    if campaign is not None:
        campaign_step, _created = CampaignStep.objects.get_or_create(
            campaign=campaign,
            missive_type=missive_type,
            defaults={"position": campaign.to_campaignstep.count() + 1},
        )
    defaults = {
        "missive_type": missive_type,
        "subject": "Test subject",
        "body_rich": "<p>hi</p>",
        "campaign_step": campaign_step,
    }
    defaults.update(overrides)
    return Missive.objects.create(**defaults)


# ---------------------------------------------------------------------------
# get_body_processors — most specific wins
# ---------------------------------------------------------------------------


def test_missive_body_processors_uses_default_when_unset(settings):
    settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS = ["myapp.proc.global"]
    missive = _make_missive()
    assert missive.get_body_processors() == ["myapp.proc.global"]


def test_missive_body_processors_falls_back_to_campaign_when_missive_empty(settings):
    settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS = ["myapp.proc.global"]
    campaign = _make_campaign(body_processors=["camp.proc"])
    missive = _make_missive(campaign=campaign)
    assert missive.get_body_processors() == ["camp.proc"]


def test_missive_body_processors_overrides_both_when_set(settings):
    settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS = ["myapp.proc.global"]
    campaign = _make_campaign(body_processors=["camp.proc"])
    missive = _make_missive(campaign=campaign, body_processors=["mis.proc"])
    assert missive.get_body_processors() == ["mis.proc"]


def test_missive_body_processors_empty_chain_disables_globally(settings):
    """An empty list at the missive level falls back to campaign / defaults
    (it's truthy-checked: ``if self.body_processors``). Use ``[]`` on settings
    or campaign to disable explicitly."""
    settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS = []
    missive = _make_missive(body_processors=[])
    assert missive.get_body_processors() == []


# ---------------------------------------------------------------------------
# get_first_document_processors — most specific wins
# ---------------------------------------------------------------------------


def test_missive_first_document_processors_uses_default(settings):
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = ["pdf.global"]
    missive = _make_missive()
    assert missive.get_first_document_processors() == ["pdf.global"]


def test_missive_first_document_processors_falls_back_to_campaign(settings):
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = ["pdf.global"]
    campaign = _make_campaign(first_document_processors=["pdf.camp"])
    missive = _make_missive(campaign=campaign)
    assert missive.get_first_document_processors() == ["pdf.camp"]


def test_missive_first_document_processors_overrides_both(settings):
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = ["pdf.global"]
    campaign = _make_campaign(first_document_processors=["pdf.camp"])
    missive = _make_missive(campaign=campaign, first_document_processors=["pdf.mis"])
    assert missive.get_first_document_processors() == ["pdf.mis"]


def test_campaign_first_document_processors_uses_default(settings):
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = ["pdf.global"]
    campaign = _make_campaign()
    assert campaign.get_first_document_processors() == ["pdf.global"]


def test_campaign_first_document_processors_overrides_default(settings):
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = ["pdf.global"]
    campaign = _make_campaign(first_document_processors=["pdf.camp"])
    assert campaign.get_first_document_processors() == ["pdf.camp"]


# ---------------------------------------------------------------------------
# get_attachment_processors — most specific wins
# ---------------------------------------------------------------------------


def test_missive_attachment_processors_uses_default(settings):
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = ["att.global"]
    missive = _make_missive()
    assert missive.get_attachment_processors() == ["att.global"]


def test_missive_attachment_processors_falls_back_to_campaign(settings):
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = ["att.global"]
    campaign = _make_campaign(attachment_processors=["att.camp"])
    missive = _make_missive(campaign=campaign)
    assert missive.get_attachment_processors() == ["att.camp"]


def test_missive_attachment_processors_overrides_both(settings):
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = ["att.global"]
    campaign = _make_campaign(attachment_processors=["att.camp"])
    missive = _make_missive(campaign=campaign, attachment_processors=["att.mis"])
    assert missive.get_attachment_processors() == ["att.mis"]


def test_campaign_attachment_processors_uses_default(settings):
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = ["att.global"]
    campaign = _make_campaign()
    assert campaign.get_attachment_processors() == ["att.global"]


# ---------------------------------------------------------------------------
# body_to_pdf — runs the chain with missive/context
# ---------------------------------------------------------------------------


def test_body_to_pdf_runs_chain_with_missive_and_context(settings):
    """``body_to_pdf`` must invoke the resolved chain with missive +
    runtime kwargs forwarded as ``context``, and propagate the campaign."""
    _renderer_calls.clear()
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_processor_integration._captured_renderer",
    ]

    campaign = _make_campaign()
    missive = _make_missive(campaign=campaign)

    out = missive.body_to_pdf(postal_recipient_pk=42)

    assert out == b"%PDF-FAKE"
    assert len(_renderer_calls) == 1
    call = _renderer_calls[0]
    assert call["missive"].pk == missive.pk
    assert call["pdf_bytes_in"] is None
    assert call["campaign"] is not None and call["campaign"].pk == campaign.pk
    assert call["context"]["postal_recipient_pk"] == 42


def test_body_to_pdf_returns_none_when_chain_disabled(settings):
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = []
    missive = _make_missive()
    assert missive.body_to_pdf() is None


def test_body_to_pdf_runs_class_based_processor_with_kwargs(settings):
    """Per-entry kwargs must reach the processor instance."""
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        ["tests.test_processor_integration._CapturingProcessor", {"sentinel": "hello"}],
    ]
    missive = _make_missive()
    out = missive.body_to_pdf()
    assert out == b"%PDF-CLS-hello"


def test_body_to_pdf_chain_runs_in_order(settings):
    """Renderer first, postprocessor second; postprocessor sees renderer's output."""
    _renderer_calls.clear()
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
        "tests.test_processor_integration._captured_renderer",
        "tests.test_processor_integration._post_appender",
    ]
    missive = _make_missive()
    out = missive.body_to_pdf()
    assert out == b"%PDF-FAKE + post"


def _post_appender(missive, pdf_bytes, *, campaign=None, context=None, **kwargs):
    return (pdf_bytes or b"") + b" + post"


# ---------------------------------------------------------------------------
# Body processors run on *_compiled properties
# ---------------------------------------------------------------------------


def test_body_rich_compiled_runs_default_chain(settings):
    """``body_rich_compiled`` runs the template processor first (renders
    ``{{ var }}``) and any subsequent processors in order."""
    settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS = [
        "django_pymissive.processors.body.django_template.django_template_processor",
        "tests.test_processor_integration._tag_appender",
    ]
    missive = _make_missive(
        body_rich="<p>Hello {{ name }}</p>",
        additional_context={"name": "Alice"},
    )
    out = missive.body_rich_compiled
    assert "Hello Alice" in out
    assert out.endswith("__TAG__")


def test_body_rich_compiled_uses_missive_processors_when_set(settings):
    """Missive-level chain wins over campaign and defaults."""
    settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS = [
        "django_pymissive.processors.body.django_template.django_template_processor",
    ]
    missive = _make_missive(
        body_rich="<p>Hello {{ name }}</p>",
        additional_context={"name": "Bob"},
        body_processors=[
            "django_pymissive.processors.body.django_template.django_template_processor",
            ["tests.test_processor_integration._tag_appender", {"tag": "MIS_ONLY"}],
        ],
    )
    out = missive.body_rich_compiled
    assert "Hello Bob" in out
    assert out.endswith("MIS_ONLY")


def test_subject_compiled_runs_chain(settings):
    settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS = [
        "django_pymissive.processors.body.django_template.django_template_processor",
    ]
    missive = _make_missive(
        subject="Hi {{ user }}!",
        additional_context={"user": "Alice"},
    )
    assert missive.subject_compiled == "Hi Alice!"


def test_body_rich_compiled_returns_empty_on_processor_error(settings):
    """A buggy processor must not crash preview — falls back to ''."""
    settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS = [
        "tests.test_processor_integration._exploding_body_processor",
    ]
    missive = _make_missive(body_rich="<p>hi</p>")
    assert missive.body_rich_compiled == ""


def _tag_appender(content, *, missive=None, campaign=None, field_name=None, context=None, tag="__TAG__", **kwargs):
    return f"{content}{tag}"


def _exploding_body_processor(content, **kwargs):
    raise RuntimeError("boom")


def test_campaign_step_accepts_an_allowed_processor(settings):
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = ["myapp"]
    campaign = _make_campaign()
    step = CampaignStep(
        campaign=campaign,
        position=1,
        missive_type="email",
        body_processors=["myapp.hooks.build"],
        build_target_processors=["django_pymissive.processors.build_target.build_target_processor"],
    )

    step.full_clean()


def test_campaign_step_refuses_a_processor_outside_the_allowlist(settings):
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = ["myapp"]
    campaign = _make_campaign()
    step = CampaignStep(
        campaign=campaign,
        position=1,
        missive_type="email",
        body_processors=[{"processor": "os.system", "kwargs": {}}],
    )

    with pytest.raises(ValidationError) as exc:
        step.full_clean()

    assert list(exc.value.message_dict) == ["body_processors"]
    assert "os.system" in exc.value.message_dict["body_processors"][0]


def test_campaign_step_validates_build_target_processors(settings):
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = ["myapp"]
    campaign = _make_campaign()
    step = CampaignStep(
        campaign=campaign,
        position=1,
        missive_type="email",
        build_target_processors=["subprocess.run"],
    )

    with pytest.raises(ValidationError) as exc:
        step.full_clean()

    assert "build_target_processors" in exc.value.message_dict
    assert "subprocess.run" in exc.value.message_dict["build_target_processors"][0]


def test_processor_chain_prefers_missive_then_step_then_campaign(settings):
    settings.PYMISSIVE_DEFAULT_BODY_PROCESSORS = ["global.proc"]
    settings.PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = ["global.pdf"]
    settings.PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = ["global.att"]
    campaign = MissiveCampaign.objects.create(
        subject="Campaign",
        body_processors=["campaign.body"],
        first_document_processors=["campaign.pdf"],
        attachment_processors=["campaign.att"],
    )
    step = CampaignStep.objects.create(
        campaign=campaign,
        position=1,
        missive_type="email",
        body_processors=["step.body"],
        first_document_processors=["step.pdf"],
        attachment_processors=["step.att"],
    )
    missive = Missive.objects.create(
        campaign_step=step,
        missive_type="email",
        subject="Hello",
        body_processors=["missive.body"],
        first_document_processors=["missive.pdf"],
        attachment_processors=["missive.att"],
    )

    assert missive.get_body_processors() == ["missive.body"]
    assert missive.get_first_document_processors() == ["missive.pdf"]
    assert missive.get_attachment_processors() == ["missive.att"]

    missive.body_processors = []
    missive.first_document_processors = []
    missive.attachment_processors = []
    missive.save(update_fields=["body_processors", "first_document_processors", "attachment_processors"])
    missive = Missive.objects.get(pk=missive.pk)
    assert missive.get_body_processors() == ["step.body"]
    assert missive.get_first_document_processors() == ["step.pdf"]
    assert missive.get_attachment_processors() == ["step.att"]

    step.body_processors = []
    step.first_document_processors = []
    step.attachment_processors = []
    step.save(update_fields=["body_processors", "first_document_processors", "attachment_processors"])
    missive = Missive.objects.get(pk=missive.pk)
    assert missive.get_body_processors() == ["campaign.body"]
    assert missive.get_first_document_processors() == ["campaign.pdf"]
    assert missive.get_attachment_processors() == ["campaign.att"]

    campaign.body_processors = []
    campaign.first_document_processors = []
    campaign.attachment_processors = []
    campaign.save(update_fields=["body_processors", "first_document_processors", "attachment_processors"])
    missive = Missive.objects.get(pk=missive.pk)
    assert missive.get_body_processors() == ["global.proc"]
    assert missive.get_first_document_processors() == ["global.pdf"]
    assert missive.get_attachment_processors() == ["global.att"]
