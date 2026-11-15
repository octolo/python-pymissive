# Consolidated cleanup after campaign-step data preparation.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('django_pymissive', '0040_delete_phonecampaignstep_delete_postalcampaignstep_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="campaigntarget",
            name="uniq_campaigntarget_pending",
        ),
        migrations.RemoveConstraint(
            model_name="campaigntarget",
            name="uniq_campaigntarget_pending_step",
        ),
        migrations.RemoveIndex(
            model_name="campaigntarget",
            name="campaigntarget_camp_type",
        ),
        migrations.AlterField(
            model_name="campaigntarget",
            name="campaign_step",
            field=models.ForeignKey(
                help_text="Step this target is selected on.",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="to_campaigntarget",
                to="django_pymissive.campaignstep",
                verbose_name="Campaign step",
            ),
        ),
        migrations.AlterField(
            model_name="campaigntarget",
            name="missive_type",
            field=models.CharField(
                choices=[
                    ("letter", "Simple letter"),
                    ("registered_letter", "Registered letter"),
                    ("hand_delivery", "Hand delivery"),
                    ("ere", "Electronic registered email (ERE)"),
                    ("email", "Email"),
                    ("email_marketing", "Marketing email"),
                    ("sms", "SMS"),
                    ("rcs", "RCS (Rich SMS)"),
                    ("voice_call", "Automated voice call"),
                    ("notification", "In-app notification"),
                    ("push_notification", "Mobile push notification"),
                    ("branded", "Branded App messaging (WhatsApp, Slack, etc.)"),
                ],
                default="",
                help_text="Channel this target is selected on (email, sms, letter, …).",
                max_length=50,
                verbose_name="Missive type",
            ),
        ),
        migrations.RemoveField(
            model_name="campaigntarget",
            name="missive_type",
        ),
        migrations.AddIndex(
            model_name="campaigntarget",
            index=models.Index(
                fields=["campaign", "campaign_step"],
                name="campaigntarget_camp_step",
            ),
        ),
        migrations.AddConstraint(
            model_name="campaigntarget",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("abandoned_at__isnull", True),
                    ("missive__isnull", True),
                ),
                fields=("campaign", "content_type", "object_id", "campaign_step"),
                name="uniq_campaigntarget_pending_step",
            ),
        ),
        migrations.RemoveField(
            model_name="missivescheduledcampaign",
            name="missive_type",
        ),
        migrations.RemoveField(
            model_name="campaignstep",
            name="acknowledgement",
        ),
        migrations.RemoveField(
            model_name="campaignstep",
            name="delivery_mode",
        ),
        migrations.RemoveField(
            model_name="campaignstep",
            name="priority",
        ),
        migrations.RemoveField(
            model_name="missive",
            name="acknowledgement",
        ),
        migrations.RemoveField(
            model_name="missive",
            name="delivery_mode",
        ),
        migrations.RemoveField(
            model_name="missive",
            name="priority",
        ),
    ]
