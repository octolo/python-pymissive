from django_pymissive.models.campaign import MissiveCampaign
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


def test_campaign_exposes_read_more_for_each_rich_snapshot(settings):
    settings.PYMISSIVE_SNAPSHOT_HTML_READ_MORE_LENGTH = 5
    campaign = MissiveCampaign(
        subject="Campaign",
        description_snapshot_html="<p>Description</p>",
        email_body_rich_snapshot_html="<p>Email body</p>",
        phone_body_rich_snapshot_html="<p>Phone body</p>",
        first_document_snapshot_html="<p>First document</p>",
    )

    assert campaign.description_snapshot_html_read_more == "<p>Desc…</p>"
    assert campaign.email_body_rich_snapshot_html_read_more == "<p>Emai…</p>"
    assert campaign.phone_body_rich_snapshot_html_read_more == "<p>Phon…</p>"
    assert campaign.first_document_snapshot_html_read_more == "<p>Firs…</p>"


def test_missive_resolves_snapshot_from_campaign():
    campaign = MissiveCampaign(
        subject="Campaign",
        email_body_rich_snapshot_html="<p>Email snapshot</p>",
    )
    missive = Missive(
        campaign=campaign,
        missive_type="email",
        missive_support="email",
    )

    assert (
        missive.get_locally_or_campaign_value("body_rich_snapshot_html")
        == "<p>Email snapshot</p>"
    )
