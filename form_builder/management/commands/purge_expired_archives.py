from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from form_builder.models import AuditLog, SentFormArchive
from form_builder.pdf_services import get_pdf_private_path


class Command(BaseCommand):
    help = "Purge sent archive records whose retention_until is in the past. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually delete expired archive records and orphaned PDFs.",
        )
        parser.add_argument(
            "--limit", type=int, default=100, help="Maximum archive records to process."
        )
        parser.add_argument(
            "--delete-files",
            action="store_true",
            help="Also delete orphaned PDF files from PRIVATE_DOCUMENT_ROOT.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        limit = options["limit"]
        confirm = options["confirm"]
        delete_files = options["delete_files"]
        archives = list(
            SentFormArchive.objects.select_related("form", "form_entry", "bewohner", "pdf_document")
            .filter(retention_until__isnull=False, retention_until__lte=now)
            .order_by("retention_until", "archived_at")[:limit]
        )
        if not confirm:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run: {len(archives)} abgelaufene Archivdatensaetze gefunden. Mit --confirm wirklich loeschen."
                )
            )
            return

        deleted_archives = 0
        deleted_pdfs = 0
        deleted_files = 0
        for archive in archives:
            pdf = archive.pdf_document
            with transaction.atomic():
                AuditLog.objects.create(
                    actor=None,
                    event_type=AuditLog.EventType.DELETED,
                    target_model="SentFormArchive",
                    target_id=archive.pk,
                    bewohner=archive.bewohner,
                    form=archive.form,
                    form_entry=archive.form_entry,
                    message="Archivdatensatz wurde nach Ablauf der Aufbewahrung geloescht.",
                    metadata={
                        "retention_until": (
                            archive.retention_until.isoformat() if archive.retention_until else ""
                        ),
                        "pdf_document_id": str(pdf.pk) if pdf else "",
                        "delete_files": delete_files,
                    },
                )
                archive.delete()
                deleted_archives += 1

                if (
                    pdf
                    and not pdf.archive_records.exists()
                    and not pdf.archived_sent_records.exists()
                    and not pdf.outbox_items.exists()
                ):
                    pdf_path = get_pdf_private_path(pdf)
                    pdf.delete()
                    deleted_pdfs += 1
                    if delete_files and pdf_path.exists():
                        try:
                            pdf_path.unlink()
                            deleted_files += 1
                        except OSError as exc:
                            raise CommandError(
                                f"PDF-Datei konnte nicht geloescht werden: {pdf_path}: {exc}"
                            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Geloescht: {deleted_archives} Archivdatensatz/-saetze, {deleted_pdfs} orphan PDF-Datensatz/-saetze, {deleted_files} Datei(en)."
            )
        )
