from django.core.management.base import BaseCommand

from form_builder.models import AuditLog


class Command(BaseCommand):
    help = "Verify the tamper-evident AuditLog hash chain."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=0, help="Optional maximum number of newest logs to verify."
        )

    def handle(self, *args, **options):
        queryset = AuditLog.objects.order_by("occurred_at", "id")
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        expected_previous = ""
        checked = 0
        errors = 0
        for log in queryset:
            checked += 1
            calculated = log.calculate_entry_hash()
            if log.previous_hash != expected_previous:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Hash-chain break at {log.id}: previous_hash={log.previous_hash or '-'} expected={expected_previous or '-'}"
                    )
                )
            if log.entry_hash != calculated:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Hash mismatch at {log.id}: entry_hash={log.entry_hash or '-'} calculated={calculated}"
                    )
                )
            expected_previous = log.entry_hash or calculated

        if errors:
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(f"AuditLog OK: {checked} Eintrag/Eintraege geprueft."))
