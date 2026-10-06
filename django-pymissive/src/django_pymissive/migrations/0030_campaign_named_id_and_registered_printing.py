import re
import unicodedata

import namedid.fields
from django.db import migrations, models


def _slug(value: str) -> str:
    string_value = unicodedata.normalize("NFD", str(value or ""))
    string_value = "".join(
        c for c in string_value if unicodedata.category(c) != "Mn"
    )
    string_value = string_value.lower().replace(" ", "-")
    string_value = re.sub(r"[^\w\-]", "", string_value)
    string_value = re.sub(r"-+", "-", string_value).strip("-")
    return string_value or "campaign"


def populate_named_ids(apps, schema_editor):
    Campaign = apps.get_model("django_pymissive", "MissiveCampaign")
    taken = set()
    for campaign in Campaign.objects.order_by("created_at", "pk").iterator():
        base = _slug(campaign.subject)
        value = base
        counter = 1
        while value in taken:
            value = f"{base}-{counter}"
            counter += 1
        taken.add(value)
        Campaign.objects.filter(pk=campaign.pk).update(named_id=value)


class Migration(migrations.Migration):

    dependencies = [
        ("django_pymissive", "0029_missive_printing_defaults"),
    ]

    operations = [
        migrations.AddField(
            model_name="missivecampaign",
            name="named_id",
            field=namedid.fields.NamedIDField(
                blank=True,
                generator="django_pymissive.generators.campaign_named_id",
                help_text="Unique identifier generated from the campaign subject",
                max_length=255,
                null=True,
                source_fields=["subject"],
                verbose_name="Named ID",
            ),
        ),
        migrations.RunPython(populate_named_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="missivecampaign",
            name="named_id",
            field=namedid.fields.NamedIDField(
                generator="django_pymissive.generators.campaign_named_id",
                help_text="Unique identifier generated from the campaign subject",
                max_length=255,
                source_fields=["subject"],
                verbose_name="Named ID",
            ),
        ),
        migrations.AlterField(
            model_name="missivecampaign",
            name="color_printing_letter",
            field=models.BooleanField(
                default=False,
                help_text="Print the simple letter in color",
                verbose_name="Color printing (letter)",
            ),
        ),
        migrations.AlterField(
            model_name="missivecampaign",
            name="duplex_printing_letter",
            field=models.BooleanField(
                default=True,
                help_text="Print the simple letter on both sides (recto verso)",
                verbose_name="Duplex printing (letter)",
            ),
        ),
        migrations.AddField(
            model_name="missivecampaign",
            name="color_printing_registered_letter",
            field=models.BooleanField(
                default=False,
                help_text="Print the registered letter in color",
                verbose_name="Color printing (registered letter)",
            ),
        ),
        migrations.AddField(
            model_name="missivecampaign",
            name="duplex_printing_registered_letter",
            field=models.BooleanField(
                default=True,
                help_text="Print the registered letter on both sides (recto verso)",
                verbose_name="Duplex printing (registered letter)",
            ),
        ),
    ]
