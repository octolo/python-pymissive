from django.db import migrations, models


def request_to_submitted(apps, schema_editor):
    """Local send used ``request``; that key is now reserved for the provider."""
    MissiveEvent = apps.get_model("django_pymissive", "MissiveEvent")
    MissiveEvent.objects.filter(event="request", client_initiated=True).update(
        event="submitted"
    )


def submitted_to_request(apps, schema_editor):
    MissiveEvent = apps.get_model("django_pymissive", "MissiveEvent")
    MissiveEvent.objects.filter(event="submitted", client_initiated=True).update(
        event="request"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("django_pymissive", "0025_missiveevent_unique_business_key"),
    ]

    operations = [
        migrations.AlterField(
            model_name="missiveevent",
            name="event",
            field=models.CharField(
                blank=True,
                choices=[
                    ("delivered", "Delivered"),
                    ("opened", "Opened"),
                    ("read", "Read"),
                    ("clicked", "Clicked"),
                    ("proofs_of_delivery", "Proofs of Delivery"),
                    ("untreated", "Untreated"),
                    ("draft", "Draft"),
                    ("sent", "Sent"),
                    ("accepted", "Accepted"),
                    ("processed", "Processed"),
                    ("deposit_proof", "Deposit proof"),
                    ("proof_of_content", "Proof of content"),
                    ("archived", "Archived"),
                    ("attempted_delivery", "Attempted delivery"),
                    ("prepare", "Prepare"),
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("queued", "Queued"),
                    ("proxy", "Proxy"),
                    ("submitted", "Submitted"),
                    ("request", "Request"),
                    ("deferred", "Deferred"),
                    ("scheduled", "Scheduled"),
                    ("unknown", "Unknown"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                    ("hard_bounce", "Hard bounce"),
                    ("soft_bounce", "Soft bounce"),
                    ("dropped", "Dropped"),
                    ("spam", "Spam"),
                    ("spam_report", "Spam report"),
                    ("blocked", "Blocked"),
                    ("rejected", "Rejected"),
                    ("refused", "Refused"),
                    ("invalid", "Invalid"),
                    ("carrier_rejected", "Carrier rejected"),
                    ("undelivered", "Undelivered"),
                    ("unsubscribe", "Unsubscribe"),
                    ("suppressed", "Suppressed"),
                    ("mailbox_full", "Mailbox full"),
                    ("domain_not_found", "Domain not found"),
                    ("error", "Error"),
                ],
                help_text="Event type (sent, delivered, read, failed, etc.)",
                max_length=50,
                null=True,
                verbose_name="Event",
            ),
        ),
        migrations.RunPython(request_to_submitted, submitted_to_request),
    ]
