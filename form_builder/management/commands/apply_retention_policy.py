from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from form_builder.retention_services import apply_retention_policy


class Command(BaseCommand):
    help = "Apply or dry-run retention policy for archived form entries."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually anonymize eligible entry data.")
        parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run mode; writes nothing.")
        parser.add_argument("--limit", type=int, default=None, help="Maximum number of archive records to process.")

    def handle(self, *args, **options):
        if options["apply"] and options["dry_run"]:
            raise CommandError("Bitte entweder --apply oder --dry-run verwenden, nicht beides.")
        dry_run = not options["apply"]
        result = apply_retention_policy(dry_run=dry_run, limit=options.get("limit"))
        self.stdout.write(self.style.SUCCESS(result.summary_de()))
