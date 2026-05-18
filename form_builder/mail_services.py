from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from .models import AuditLog, OutboxItem, SentFormArchive
from .pdf_services import get_pdf_private_path


@dataclass(frozen=True)
class OutboxProcessingResult:
    processed: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0

    def summary_de(self) -> str:
        return (
            f"{self.processed} verarbeitet, "
            f"{self.sent} versendet, "
            f"{self.failed} fehlgeschlagen, "
            f"{self.skipped} uebersprungen."
        )


def get_due_outbox_queryset(limit: int | None = None, *, for_update: bool = False):
    now = timezone.now()
    queryset = (
        OutboxItem.objects.select_related(
            "form",
            "form_entry",
            "bewohner",
            "recipient",
            "pdf_document",
        )
        .filter(status=OutboxItem.DeliveryStatus.PENDING)
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .order_by("next_attempt_at", "created_at")
    )
    if for_update:
        select_for_update_kwargs = {}
        if connection.features.has_select_for_update_skip_locked:
            select_for_update_kwargs["skip_locked"] = True
        queryset = queryset.select_for_update(**select_for_update_kwargs)
    if limit:
        queryset = queryset[:limit]
    return queryset


def build_outbox_email(outbox_item: OutboxItem, *, connection=None) -> EmailMessage:
    recipient = outbox_item.recipient
    to, cc, bcc = [], [], []
    if recipient.recipient_type == recipient.RecipientType.CC:
        cc.append(recipient.email)
    elif recipient.recipient_type == recipient.RecipientType.BCC:
        bcc.append(recipient.email)
    else:
        to.append(recipient.email)

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    subject = outbox_item.subject or f"{outbox_item.form.title} - {outbox_item.bewohner}"
    body = outbox_item.body or "Anbei erhalten Sie das angeforderte Formular als PDF."

    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email,
        to=to,
        cc=cc,
        bcc=bcc,
        connection=connection,
    )

    if outbox_item.pdf_document_id:
        pdf_path = get_pdf_private_path(outbox_item.pdf_document)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF-Datei nicht gefunden: {pdf_path}")
        message.attach_file(
            str(pdf_path), mimetype=outbox_item.pdf_document.content_type or "application/pdf"
        )

    return message


def mark_outbox_failed(outbox_item: OutboxItem, *, error: Exception) -> None:
    now = timezone.now()
    outbox_item.attempt_count += 1
    outbox_item.last_attempt_at = now
    outbox_item.last_error_code = error.__class__.__name__[:100]
    outbox_item.last_error_message = str(error)[:2000]
    if outbox_item.attempt_count >= outbox_item.max_attempts:
        outbox_item.status = OutboxItem.DeliveryStatus.FAILED
        outbox_item.failed_at = now
        outbox_item.next_attempt_at = None
    else:
        outbox_item.next_attempt_at = now + timedelta(minutes=15 * outbox_item.attempt_count)
    outbox_item.save(
        update_fields=[
            "attempt_count",
            "last_attempt_at",
            "last_error_code",
            "last_error_message",
            "status",
            "failed_at",
            "next_attempt_at",
            "updated_at",
        ]
    )
    AuditLog.objects.create(
        actor=outbox_item.updated_by,
        event_type=AuditLog.EventType.STATUS_CHANGED,
        target_model="OutboxItem",
        target_id=outbox_item.pk,
        bewohner=outbox_item.bewohner,
        form=outbox_item.form,
        form_entry=outbox_item.form_entry,
        message="Versandvorgang ist fehlgeschlagen.",
        metadata={
            "outbox_item_id": str(outbox_item.pk),
            "error_code": outbox_item.last_error_code,
            "attempt_count": outbox_item.attempt_count,
            "status": outbox_item.status,
        },
    )


def archive_entry_if_all_outbox_sent(outbox_item: OutboxItem) -> None:
    form_entry = outbox_item.form_entry
    has_unsent_required_items = form_entry.outbox_items.filter(
        status__in=[
            OutboxItem.DeliveryStatus.PENDING,
            OutboxItem.DeliveryStatus.FAILED,
        ]
    ).exists()
    if has_unsent_required_items:
        if form_entry.status != form_entry.EntryStatus.READY_TO_SEND:
            form_entry.status = form_entry.EntryStatus.READY_TO_SEND
            form_entry.updated_by = outbox_item.updated_by
            form_entry.save(update_fields=["status", "updated_by", "updated_at"])
        return

    now = timezone.now()
    form_entry.status = form_entry.EntryStatus.ARCHIVED
    form_entry.archived_at = now
    form_entry.updated_by = outbox_item.updated_by
    form_entry.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])


def mark_outbox_sent(outbox_item: OutboxItem, *, provider_payload: dict | None = None) -> None:
    now = timezone.now()
    with transaction.atomic():
        outbox_item.status = OutboxItem.DeliveryStatus.SENT
        outbox_item.attempt_count += 1
        outbox_item.last_attempt_at = now
        outbox_item.sent_at = now
        outbox_item.failed_at = None
        outbox_item.next_attempt_at = None
        outbox_item.last_error_code = ""
        outbox_item.last_error_message = ""
        outbox_item.provider_payload = provider_payload or {}
        outbox_item.save(
            update_fields=[
                "status",
                "attempt_count",
                "last_attempt_at",
                "sent_at",
                "failed_at",
                "next_attempt_at",
                "last_error_code",
                "last_error_message",
                "provider_payload",
                "updated_at",
            ]
        )

        SentFormArchive.objects.get_or_create(
            outbox_item=outbox_item,
            defaults={
                "form": outbox_item.form,
                "form_entry": outbox_item.form_entry,
                "bewohner": outbox_item.bewohner,
                "pdf_document": outbox_item.pdf_document,
                "sent_at": now,
                "recipient_snapshot": {
                    "name": outbox_item.recipient.name,
                    "email": outbox_item.recipient.email,
                    "recipient_type": outbox_item.recipient.recipient_type,
                    "channel": outbox_item.recipient.channel,
                },
                "delivery_snapshot": {
                    "subject": outbox_item.subject,
                    "channel": outbox_item.channel,
                    "provider_payload": outbox_item.provider_payload,
                    "outbox_item_id": str(outbox_item.pk),
                },
                "retention_until": now + timedelta(days=outbox_item.form.retention_period_days),
                "archive_metadata": {
                    "source": "outbox",
                    "pdf_sha256": (
                        outbox_item.pdf_document.sha256 if outbox_item.pdf_document_id else ""
                    ),
                },
                "created_by": outbox_item.created_by,
                "updated_by": outbox_item.updated_by,
            },
        )

        AuditLog.objects.create(
            actor=outbox_item.updated_by,
            event_type=AuditLog.EventType.SENT,
            target_model="OutboxItem",
            target_id=outbox_item.pk,
            bewohner=outbox_item.bewohner,
            form=outbox_item.form,
            form_entry=outbox_item.form_entry,
            message="Formular wurde erfolgreich an einen Empfaenger versendet.",
            metadata={
                "outbox_item_id": str(outbox_item.pk),
                "recipient_email": outbox_item.recipient.email,
                "pdf_document_id": (
                    str(outbox_item.pdf_document_id) if outbox_item.pdf_document_id else None
                ),
            },
        )
        archive_entry_if_all_outbox_sent(outbox_item)


def send_outbox_item(outbox_item: OutboxItem, *, connection=None) -> bool:
    if outbox_item.status != OutboxItem.DeliveryStatus.PENDING:
        return False

    try:
        message = build_outbox_email(outbox_item, connection=connection)
        sent_count = message.send(fail_silently=False)
        if sent_count < 1:
            raise RuntimeError("E-Mail-Backend hat keinen Versand bestaetigt.")
    except Exception as exc:  # noqa: BLE001 - persist operational failure details for audit/retry.
        mark_outbox_failed(outbox_item, error=exc)
        return False

    backend_name = getattr(settings, "EMAIL_BACKEND", "")
    mark_outbox_sent(
        outbox_item,
        provider_payload={
            "backend": backend_name,
            "sent_count": sent_count,
            "processed_at": timezone.now().isoformat(),
        },
    )
    return True


def process_outbox_queue(*, limit: int | None = 20) -> OutboxProcessingResult:
    processed = 0
    sent = 0
    failed = 0
    skipped = 0
    max_items = limit or 1000000

    with get_connection(fail_silently=False) as mail_connection:
        while processed < max_items:
            with transaction.atomic():
                due_items = list(get_due_outbox_queryset(limit=1, for_update=True))
                if not due_items:
                    break
                outbox_item = due_items[0]
                processed += 1
                if outbox_item.status != OutboxItem.DeliveryStatus.PENDING:
                    skipped += 1
                    continue
                ok = send_outbox_item(outbox_item, connection=mail_connection)
                if ok:
                    sent += 1
                else:
                    failed += 1

    return OutboxProcessingResult(processed=processed, sent=sent, failed=failed, skipped=skipped)
