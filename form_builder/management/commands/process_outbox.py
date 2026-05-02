from django.core.management.base import BaseCommand

from form_builder.mail_services import process_outbox_queue


class Command(BaseCommand):
    help = "Send due pending outbox items and archive successful deliveries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Maximum number of pending outbox items to process in this run.",
        )

    def handle(self, *args, **options):
        result = process_outbox_queue(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(result.summary_de()))
