from django.core.management.base import BaseCommand

from form_builder.schedule_services import run_due_schedules

class Command(BaseCommand):
    help = "Process due form schedules and queue approved entries into the outbox."

    def add_arguments(self, parser):
        parser.add_argument("--limit-per-schedule", type=int, default=100)

    def handle(self, *args, **options):
        result = run_due_schedules(limit_per_schedule=options["limit_per_schedule"])
        self.stdout.write(self.style.SUCCESS(result.summary_de()))
        for skipped in result.skipped:
            self.stdout.write(self.style.WARNING(f"Uebersprungen: {skipped}"))
        for error in result.errors:
            self.stdout.write(self.style.ERROR(f"Fehler: {error}"))
