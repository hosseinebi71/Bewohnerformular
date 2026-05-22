from django.core.management.base import BaseCommand

from form_builder.action_item_services import process_reminders


class Command(BaseCommand):
    help = "Generate reminder/escalation events for overdue ActionItems and pending reviews."

    def add_arguments(self, parser):
        parser.add_argument("--due-soon-days", type=int, default=2)
        parser.add_argument("--escalate-after-days", type=int, default=3)

    def handle(self, *args, **options):
        result = process_reminders(
            due_soon_days=options["due_soon_days"],
            escalate_after_days=options["escalate_after_days"],
        )
        self.stdout.write(self.style.SUCCESS(result.summary_de()))
