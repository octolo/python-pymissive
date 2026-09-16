from django.db import migrations, models
from django.db.models import Count, Min


def collapse_duplicate_events(apps, schema_editor):
    """Keep the oldest row of each business key so AddConstraint can apply."""
    MissiveEvent = apps.get_model("django_pymissive", "MissiveEvent")

    for group in (
        MissiveEvent.objects.filter(missive_id__isnull=False, recipient_id__isnull=False)
        .values("missive_id", "event", "occurred_at", "recipient_id")
        .annotate(n=Count("pk"), keep=Min("pk"))
        .filter(n__gt=1)
    ):
        (
            MissiveEvent.objects.filter(
                missive_id=group["missive_id"],
                event=group["event"],
                occurred_at=group["occurred_at"],
                recipient_id=group["recipient_id"],
            )
            .exclude(pk=group["keep"])
            .delete()
        )

    for group in (
        MissiveEvent.objects.filter(missive_id__isnull=False, recipient_id__isnull=True)
        .values("missive_id", "event", "occurred_at")
        .annotate(n=Count("pk"), keep=Min("pk"))
        .filter(n__gt=1)
    ):
        (
            MissiveEvent.objects.filter(
                missive_id=group["missive_id"],
                event=group["event"],
                occurred_at=group["occurred_at"],
                recipient_id__isnull=True,
            )
            .exclude(pk=group["keep"])
            .delete()
        )


class Migration(migrations.Migration):

    dependencies = [
        ("django_pymissive", "0024_alter_missiveconfig_missive_type"),
    ]

    operations = [
        migrations.RunPython(collapse_duplicate_events, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="missiveevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(missive__isnull=False, recipient__isnull=False),
                fields=("missive", "event", "occurred_at", "recipient"),
                name="uniq_missive_event_at_recipient",
            ),
        ),
        migrations.AddConstraint(
            model_name="missiveevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(missive__isnull=False, recipient__isnull=True),
                fields=("missive", "event", "occurred_at"),
                name="uniq_missive_event_at_no_recipient",
            ),
        ),
    ]
