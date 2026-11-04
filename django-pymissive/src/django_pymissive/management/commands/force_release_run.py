"""Force-release a scheduled campaign run whose worker is known to be dead."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from ...models.scheduler import MissiveScheduledCampaign


class Command(BaseCommand):
    help = "End a running campaign send and reopen its unaccepted PROCESSING missives."

    def add_arguments(self, parser):
        parser.add_argument("run_id", help="UUID of the scheduled campaign run.")
        parser.add_argument(
            "--reason",
            default="",
            help="Reason recorded in additional_config['last_error'].",
        )

    def handle(self, *args, **options):
        try:
            run = MissiveScheduledCampaign.objects.get(pk=options["run_id"])
            reopened = run.force_release(options["reason"])
        except MissiveScheduledCampaign.DoesNotExist as exc:
            raise CommandError(f"Scheduled campaign run {options['run_id']} does not exist.") from exc
        except (ValidationError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Released run {run.pk}; reopened {reopened} processing missive(s).",
            )
        )
