"""Rename body fields for clearer semantics.

Missive:
  body_html  → body_rich

Campaign:
  body_html  → email_body_rich
  body_text  → email_body_text
  body_sms   → phone_body_text
  (new)        phone_body_rich
"""

from django.db import migrations, models
import django_pymissive.fields


class Migration(migrations.Migration):

    dependencies = [
        ("django_pymissive", "0011_alter_missivescheduledcampaign_options_and_more"),
    ]

    operations = [
        # ── Missive ──────────────────────────────────────────────────────────
        migrations.RenameField(
            model_name="missive",
            old_name="body_html",
            new_name="body_rich",
        ),
        migrations.AlterField(
            model_name="missive",
            name="body_rich",
            field=django_pymissive.fields.RichTextField(
                blank=True,
                null=True,
                verbose_name="Rich body",
                help_text="Rich content body (HTML, RTF, …) — email, LRE, etc.",
            ),
        ),

        # ── Campaign — renames ───────────────────────────────────────────────
        migrations.RenameField(
            model_name="missivecampaign",
            old_name="body_html",
            new_name="email_body_rich",
        ),
        migrations.AlterField(
            model_name="missivecampaign",
            name="email_body_rich",
            field=django_pymissive.fields.RichTextField(
                blank=True,
                verbose_name="Email rich body",
                help_text="Rich content body for email (HTML, RTF, …)",
            ),
        ),
        migrations.RenameField(
            model_name="missivecampaign",
            old_name="body_text",
            new_name="email_body_text",
        ),
        migrations.AlterField(
            model_name="missivecampaign",
            name="email_body_text",
            field=models.TextField(
                blank=True,
                verbose_name="Email plain text body",
                help_text="Plain text body for email",
            ),
        ),
        migrations.RenameField(
            model_name="missivecampaign",
            old_name="body_sms",
            new_name="phone_body_text",
        ),
        migrations.AlterField(
            model_name="missivecampaign",
            name="phone_body_text",
            field=models.TextField(
                blank=True,
                verbose_name="SMS / App plain text body",
                help_text="Plain text body for SMS, push and messaging apps",
            ),
        ),

        # ── Campaign — new field ─────────────────────────────────────────────
        migrations.AddField(
            model_name="missivecampaign",
            name="phone_body_rich",
            field=models.TextField(
                blank=True,
                verbose_name="SMS / App rich body",
                help_text="Rich body for rich SMS, WhatsApp, RCS, etc.",
            ),
        ),
    ]
