from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.campaign_step import CampaignStep, PostalCampaignStep
from django_pymissive.models.missive import Missive


def test_missive_snapshot_read_more_balances_html(settings):
    settings.PYMISSIVE_SNAPSHOT_HTML_READ_MORE_LENGTH = 11
    missive = Missive(
        body_rich_snapshot_html="<p>Hello <strong>world and friends</strong></p>",
    )

    excerpt = missive.body_rich_snapshot_html_read_more

    assert "friends" not in excerpt
    assert excerpt.endswith("</strong></p>")
    assert "…" in excerpt


def test_snapshot_read_more_length_defaults_for_invalid_setting(settings):
    settings.PYMISSIVE_SNAPSHOT_HTML_READ_MORE_LENGTH = "invalid"
    missive = Missive(body_rich_snapshot_html=f"<p>{'a' * 600}</p>")

    excerpt = missive.body_rich_snapshot_html_read_more

    assert excerpt.count("a") == 499
    assert excerpt.endswith("…</p>")


def test_campaign_and_steps_expose_read_more_for_rich_snapshots(settings):
    settings.PYMISSIVE_SNAPSHOT_HTML_READ_MORE_LENGTH = 5
    campaign = MissiveCampaign(
        subject="Campaign",
        description_snapshot_html="<p>Description</p>",
    )
    email = CampaignStep(
        campaign=campaign,
        position=1,
        missive_type="email",
        body_rich_snapshot_html="<p>Email body</p>",
    )
    postal = PostalCampaignStep(
        campaign=campaign,
        position=2,
        missive_type="letter",
        body_rich_snapshot_html="<p>First document</p>",
    )

    assert campaign.description_snapshot_html_read_more == "<p>Desc…</p>"
    assert email.body_rich_snapshot_html_read_more == "<p>Emai…</p>"
    assert postal.first_document_snapshot_html_read_more == "<p>Firs…</p>"


def test_missive_resolves_snapshot_from_campaign_step():
    campaign = MissiveCampaign(subject="Campaign")
    step = CampaignStep(
        id=1,
        campaign=campaign,
        position=1,
        missive_type="email",
        body_rich_snapshot_html="<p>Email snapshot</p>",
    )
    missive = Missive(
        campaign_step=step,
        missive_type="email",
        missive_support="email",
    )

    assert missive.get_locally_or_campaign_value("body_rich_snapshot_html") == "<p>Email snapshot</p>"
