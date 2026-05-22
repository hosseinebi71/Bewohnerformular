from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .audit_services import audit_event
from .models import AuditLog, FormEntry, SentFormArchive


@dataclass(frozen=True)
class RetentionResult:
    scanned: int = 0
    eligible: int = 0
    processed: int = 0
    dry_run: bool = True

    def summary_de(self) -> str:
        mode = "Trockenlauf" if self.dry_run else "Ausgefuehrt"
        return (
            f"{mode}: {self.scanned} Archivdatensaetze geprueft, "
            f"{self.eligible} faellig, {self.processed} verarbeitet."
        )


def _retention_already_processed(archive: SentFormArchive) -> bool:
    metadata = archive.archive_metadata or {}
    if not isinstance(metadata, dict):
        return False
    retention = metadata.get("retention") or {}
    return isinstance(retention, dict) and retention.get("status") == "processed"


def retention_due_queryset(*, as_of=None):
    """Return archives whose retention date has passed.

    Keep the database filter deliberately simple. Nested JSON lookups behave
    differently across SQLite/PostgreSQL when the JSON path is missing; doing
    the processed check in Python keeps tests and production behavior aligned.
    """
    as_of = as_of or timezone.now()
    return (
        SentFormArchive.objects.select_related("form", "form_entry", "bewohner")
        .filter(retention_until__isnull=False, retention_until__lte=as_of)
        .order_by("retention_until", "archived_at")
    )


def retention_candidates(
    *, as_of=None, limit: int | None = None
) -> tuple[int, list[SentFormArchive]]:
    queryset = retention_due_queryset(as_of=as_of)
    scanned = queryset.count()
    candidates: list[SentFormArchive] = []
    for archive in queryset:
        if _retention_already_processed(archive):
            continue
        candidates.append(archive)
        if limit is not None and len(candidates) >= limit:
            break
    return scanned, candidates


def _redacted_entry_payload(form_entry: FormEntry) -> dict:
    return {
        "retention_processed": True,
        "retention_processed_at": timezone.now().isoformat(),
        "previous_status": form_entry.status,
    }


def apply_retention_policy(
    *, actor=None, dry_run: bool = True, as_of=None, limit: int | None = None
) -> RetentionResult:
    """Flag/anonymize archived entries whose retention date has passed.

    Safety model:
    - dry_run never writes
    - apply does not delete database rows or files
    - entry data is cleared and the entry is moved to DELETED
    - archive metadata records exactly what happened
    - every processed archive gets an append-only audit event
    """

    scanned, candidates = retention_candidates(as_of=as_of, limit=limit)
    if dry_run:
        return RetentionResult(scanned=scanned, eligible=len(candidates), processed=0, dry_run=True)

    processed = 0
    now = timezone.now()
    with transaction.atomic():
        for archive in candidates:
            entry = archive.form_entry
            previous_status = entry.status
            entry.data = {}
            entry.validation_errors = _redacted_entry_payload(entry)
            entry.status = FormEntry.EntryStatus.DELETED
            entry.updated_by = actor if getattr(actor, "is_authenticated", False) else None
            entry.save(
                update_fields=["data", "validation_errors", "status", "updated_by", "updated_at"]
            )

            metadata = dict(archive.archive_metadata or {})
            metadata["retention"] = {
                "status": "processed",
                "processed_at": now.isoformat(),
                "mode": "anonymized_entry_data",
                "previous_entry_status": previous_status,
            }
            archive.archive_metadata = metadata
            archive.updated_by = actor if getattr(actor, "is_authenticated", False) else None
            archive.save(update_fields=["archive_metadata", "updated_by", "updated_at"])

            audit_event(
                actor=actor,
                event_type=AuditLog.EventType.DELETED,
                target_model="SentFormArchive",
                target_id=archive.pk,
                bewohner=archive.bewohner,
                form=archive.form,
                form_entry=archive.form_entry,
                message="Aufbewahrungsfrist wurde verarbeitet; Eintragsdaten wurden anonymisiert.",
                metadata={
                    "retention_until": (
                        archive.retention_until.isoformat() if archive.retention_until else None
                    ),
                    "mode": "anonymized_entry_data",
                    "previous_entry_status": previous_status,
                },
            )
            processed += 1
    return RetentionResult(
        scanned=scanned, eligible=len(candidates), processed=processed, dry_run=False
    )
