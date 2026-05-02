from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import AuditLog, FormEntry, FormRecipient, FormSchedule, OutboxItem, PDFDocument

@dataclass
class ScheduleRunResult:
    schedules_checked: int = 0
    schedules_due: int = 0
    queued: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary_de(self) -> str:
        parts = [f"{self.schedules_checked} Zeitplan/Zeitraeume geprueft", f"{self.schedules_due} faellig", f"{self.queued} Versandvorgang/Vorgaenge erzeugt"]
        if self.skipped:
            parts.append(f"{len(self.skipped)} uebersprungen")
        if self.errors:
            parts.append(f"{len(self.errors)} Fehler")
        return ", ".join(parts) + "."

def _get_schedule_timezone(schedule: FormSchedule) -> ZoneInfo:
    try:
        return ZoneInfo(schedule.timezone or "Europe/Berlin")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/Berlin")

def _parse_run_time(value: str | None) -> time:
    if not value:
        return time(8, 0)
    hour, minute = value.split(":")[:2]
    return time(int(hour), int(minute))

def compute_next_run_at(schedule: FormSchedule, *, from_time: datetime | None = None) -> datetime:
    config = schedule.config or {}
    frequency = config.get("frequency", "weekly")
    run_time = _parse_run_time(config.get("run_time", "08:00"))
    tz = _get_schedule_timezone(schedule)
    base = from_time or timezone.now()
    local_base = timezone.localtime(base, tz)
    candidate = datetime.combine(local_base.date(), run_time, tzinfo=tz)
    if frequency == "daily":
        if candidate <= local_base:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.get_current_timezone())
    target_weekday = int(config.get("weekday", 0))
    days_ahead = (target_weekday - local_base.weekday()) % 7
    candidate = datetime.combine(local_base.date() + timedelta(days=days_ahead), run_time, tzinfo=tz)
    if candidate <= local_base:
        candidate += timedelta(days=7)
    return candidate.astimezone(timezone.get_current_timezone())

def get_due_schedules(*, now: datetime | None = None):
    now = now or timezone.now()
    return (
        FormSchedule.objects.select_related("form")
        .filter(
            trigger_type=FormSchedule.TriggerType.SCHEDULED,
            status=FormSchedule.ScheduleStatus.ACTIVE,
            is_active=True,
            next_run_at__isnull=False,
            next_run_at__lte=now,
        )
        .filter(Q(start_at__isnull=True) | Q(start_at__lte=now))
        .filter(Q(end_at__isnull=True) | Q(end_at__gte=now))
        .order_by("next_run_at", "form__title", "name")
    )

def _latest_pdf_for_entry(entry: FormEntry) -> PDFDocument | None:
    return (PDFDocument.objects.filter(form_entry=entry, status=PDFDocument.GenerationStatus.GENERATED).order_by("-generated_at", "-created_at").first())

def _audit_schedule_event(*, schedule: FormSchedule, message: str, metadata: dict | None = None) -> None:
    AuditLog.objects.create(actor=None, event_type=AuditLog.EventType.STATUS_CHANGED, target_model="FormSchedule", target_id=schedule.pk, form=schedule.form, message=message, metadata=metadata or {})

def queue_entries_for_schedule(schedule: FormSchedule, *, limit: int = 100) -> int:
    recipients = list(FormRecipient.objects.filter(form=schedule.form, is_active=True, is_default=True).order_by("recipient_type", "email"))
    if not recipients:
        raise ValidationError(f"Zeitplan '{schedule.name}' hat keinen aktiven Standard-Empfaenger.")
    entries = list(FormEntry.objects.select_related("form", "bewohner")
        .filter(form=schedule.form, status=FormEntry.EntryStatus.APPROVED)
        .exclude(outbox_items__status__in=[OutboxItem.DeliveryStatus.PENDING, OutboxItem.DeliveryStatus.SENT])
        .order_by("submitted_at", "updated_at")[:limit])
    queued = 0
    for entry in entries:
        pdf_document = _latest_pdf_for_entry(entry)
        if not pdf_document:
            continue
        with transaction.atomic():
            entry.status = FormEntry.EntryStatus.READY_TO_SEND
            entry.save(update_fields=["status", "updated_at"])
            for recipient in recipients:
                OutboxItem.objects.create(form=entry.form, form_entry=entry, bewohner=entry.bewohner, schedule=schedule, recipient=recipient, pdf_document=pdf_document, status=OutboxItem.DeliveryStatus.PENDING, subject=f"{entry.form.title} - {entry.bewohner}", body="Dieses Formular wurde durch einen sicheren Zeitplan in den Ausgangskorb gestellt.", payload={"form_entry_id": str(entry.pk), "schedule_id": str(schedule.pk), "recipient_id": str(recipient.pk), "pdf_document_id": str(pdf_document.pk), "pdf_sha256": pdf_document.sha256, "queued_by": "schedule"}, next_attempt_at=timezone.now())
                queued += 1
            AuditLog.objects.create(actor=None, event_type=AuditLog.EventType.STATUS_CHANGED, target_model="FormEntry", target_id=entry.pk, bewohner=entry.bewohner, form=entry.form, form_entry=entry, message="Formulareintrag wurde durch Zeitplan in den Ausgangskorb gestellt.", metadata={"schedule_id": str(schedule.pk), "outbox_item_count": len(recipients)})
    return queued

def advance_schedule_after_run(schedule: FormSchedule, *, now: datetime) -> None:
    next_run = compute_next_run_at(schedule, from_time=now)
    if schedule.start_at and next_run < schedule.start_at:
        next_run = compute_next_run_at(schedule, from_time=schedule.start_at)
    if schedule.end_at and next_run > schedule.end_at:
        schedule.next_run_at = None
        schedule.is_active = False
        schedule.status = FormSchedule.ScheduleStatus.RETIRED
    else:
        schedule.next_run_at = next_run


def run_due_schedules(*, limit_per_schedule: int = 100, now: datetime | None = None) -> ScheduleRunResult:
    now = now or timezone.now()
    schedules = list(get_due_schedules(now=now))
    result = ScheduleRunResult(schedules_checked=len(schedules), schedules_due=len(schedules))
    for schedule in schedules:
        try:
            queued = queue_entries_for_schedule(schedule, limit=limit_per_schedule)
            result.queued += queued
            schedule.last_run_at = now
            advance_schedule_after_run(schedule, now=now)
            schedule.save(update_fields=["last_run_at", "next_run_at", "is_active", "status", "updated_at"])
            _audit_schedule_event(schedule=schedule, message="Zeitplan wurde verarbeitet.", metadata={"queued": queued, "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None, "status": schedule.status})
            if not queued:
                result.skipped.append(f"{schedule.name}: keine freigegebenen Eintraege mit PDF gefunden")
        except Exception as exc:
            result.errors.append(f"{schedule.name}: {exc}")
    return result
