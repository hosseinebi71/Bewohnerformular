from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from form_builder.models import (
    AuditLog,
    Bewohner,
    Field,
    Form,
    FormEntry,
    FormRecipient,
    FormSchedule,
    PDFDocument,
)
from form_builder.pdf_services import get_private_document_root

DEMO_FORM_KEY = "demo-wochenbericht-bewohner"
DEMO_RESIDENT_NUMBER = "DEMO-0001"
DEMO_EMAIL = "demo.empfaenger@example.com"
DEMO_SCHEDULE_NAME = "Demo - taeglicher Versandtest"
DEMO_USERNAME = "demo.admin"
DEMO_PASSWORD = "ChangeMe!12345"

DEMO_PDF_BYTES = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 120 >>
stream
BT
/F1 18 Tf
72 760 Td
(Demo PDF - Bewohner Formularsystem) Tj
/F1 11 Tf
0 -28 Td
(Dieses Dokument wurde durch seed_demo_data erzeugt.) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000253 00000 n 
0000000423 00000 n 
trailer
<< /Root 1 0 R /Size 6 >>
startxref
493
%%EOF
"""


class Command(BaseCommand):
    help = "Create professional local demo data for testing the full Bewohner form workflow."

    def add_arguments(self, parser):
        parser.add_argument("--allow-production", action="store_true")
        parser.add_argument("--skip-demo-user", action="store_true")
        parser.add_argument("--reset-demo-password", action="store_true")
        parser.add_argument("--no-force-due-schedule", action="store_true")
        parser.add_argument(
            "--fresh-entry",
            action="store_true",
            help="Create a new approved demo entry even if one exists.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_production"]:
            raise CommandError(
                "seed_demo_data is blocked when DEBUG=False. Use --allow-production only in a controlled test environment."
            )

        with transaction.atomic():
            self._ensure_groups()
            user = None if options["skip_demo_user"] else self._ensure_demo_user(options)
            bewohner = self._ensure_bewohner(user)
            form = self._ensure_form_with_fields(user)
            recipient = self._ensure_recipient(form, user)
            schedule = self._ensure_schedule(
                form, user, force_due=not options["no_force_due_schedule"]
            )
            entry = self._ensure_approved_entry(form, bewohner, user, fresh=options["fresh_entry"])
            pdf_document = self._ensure_demo_pdf(entry, user)

        self.stdout.write(self.style.SUCCESS("Demo-Daten wurden erfolgreich vorbereitet."))
        self.stdout.write("")
        if user:
            self.stdout.write(self.style.WARNING("Lokaler Demo-Login:"))
            self.stdout.write(f"  Benutzer: {DEMO_USERNAME}")
            self.stdout.write(f"  Passwort: {DEMO_PASSWORD}")
            self.stdout.write("  Nur fuer lokale Entwicklung verwenden.")
            self.stdout.write("")
        self.stdout.write("Angelegte/aktualisierte Demo-Objekte:")
        self.stdout.write(f"  Bewohner: {bewohner}")
        self.stdout.write(f"  Formular: {form.title} ({form.key})")
        self.stdout.write(f"  Empfaenger: {recipient.email}")
        self.stdout.write(f"  Zeitplan: {schedule.name} | next_run_at={schedule.next_run_at}")
        self.stdout.write(f"  Freigegebener Eintrag: {entry.public_id}")
        self.stdout.write(f"  Demo-PDF: {pdf_document.original_filename}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Naechste Tests:"))
        self.stdout.write("  python manage.py process_schedules --limit-per-schedule 100")
        self.stdout.write("  python manage.py process_outbox --limit 20")
        self.stdout.write("  python manage.py runserver")
        self.stdout.write("  http://127.0.0.1:8000/formulare/ausgangskorb/")
        self.stdout.write("  http://127.0.0.1:8000/formulare/archiv/")

    def _ensure_groups(self) -> None:
        for name in ("Admin", "Staff", "Viewer"):
            Group.objects.get_or_create(name=name)

    def _ensure_demo_user(self, options):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={
                "email": "demo.admin@example.com",
                "first_name": "Demo",
                "last_name": "Admin",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created or options["reset_demo_password"]:
            user.set_password(DEMO_PASSWORD)
        user.email = user.email or "demo.admin@example.com"
        user.first_name = user.first_name or "Demo"
        user.last_name = user.last_name or "Admin"
        user.is_staff = True
        user.is_superuser = True
        user.save()
        admin_group, _ = Group.objects.get_or_create(name="Admin")
        user.groups.add(admin_group)
        return user

    def _ensure_bewohner(self, user):
        bewohner, _ = Bewohner.objects.update_or_create(
            resident_number=DEMO_RESIDENT_NUMBER,
            defaults={
                "first_name": "Max",
                "last_name": "Mustermann",
                "date_of_birth": "1942-03-14",
                "room_label": "A-101",
                "status": Bewohner.RecordStatus.ACTIVE,
                "notes": "Lokaler Demo-Datensatz fuer Workflow-Tests.",
                "updated_by": user,
            },
        )
        if user and not bewohner.created_by_id:
            bewohner.created_by = user
            bewohner.save(update_fields=["created_by"])
        return bewohner

    def _ensure_form_with_fields(self, user):
        form, _ = Form.objects.get_or_create(
            key=DEMO_FORM_KEY,
            version=1,
            defaults={
                "title": "Demo Wochenbericht Bewohner",
                "description": "Professioneller Demo-Workflow fuer Draft, Review, PDF, Outbox und Archiv.",
                "status": Form.PublicationStatus.DRAFT,
                "review_required": True,
                "is_archivable": True,
                "retention_period_days": 3650,
                "created_by": user,
                "updated_by": user,
            },
        )
        form.title = "Demo Wochenbericht Bewohner"
        form.description = (
            "Professioneller Demo-Workflow fuer Draft, Review, PDF, Outbox und Archiv."
        )
        form.review_required = True
        form.is_archivable = True
        form.retention_period_days = 3650
        form.updated_by = user
        form.save()

        field_specs = [
            {
                "position": 1,
                "key": "datum",
                "label": "Datum",
                "field_type": Field.FieldType.DATE,
                "required": True,
            },
            {
                "position": 2,
                "key": "pkz",
                "label": "PKZ",
                "field_type": Field.FieldType.TEXT,
                "required": True,
                "placeholder": "z. B. PKZ-12345",
                "sensitivity": Field.SensitivityLevel.SENSITIVE,
            },
            {
                "position": 3,
                "key": "grund",
                "label": "Grund / Anlass",
                "field_type": Field.FieldType.SELECT,
                "required": True,
                "choices": [
                    {"value": "routine", "label": "Routine"},
                    {"value": "aenderung", "label": "Aenderung"},
                    {"value": "notiz", "label": "Notiz"},
                ],
            },
            {
                "position": 4,
                "key": "bericht",
                "label": "Bericht",
                "field_type": Field.FieldType.TEXTAREA,
                "required": True,
                "help_text": "Kurze fachliche Zusammenfassung fuer den Empfaenger.",
                "sensitivity": Field.SensitivityLevel.SENSITIVE,
            },
            {
                "position": 5,
                "key": "rueckmeldung_erforderlich",
                "label": "Rueckmeldung erforderlich",
                "field_type": Field.FieldType.BOOLEAN,
                "required": False,
                "default_value": False,
            },
        ]
        for spec in field_specs:
            Field.objects.update_or_create(
                form=form,
                key=spec["key"],
                defaults={
                    "position": spec["position"],
                    "label": spec["label"],
                    "field_type": spec["field_type"],
                    "required": spec.get("required", False),
                    "sensitivity": spec.get("sensitivity", Field.SensitivityLevel.NORMAL),
                    "placeholder": spec.get("placeholder", ""),
                    "help_text": spec.get("help_text", ""),
                    "default_value": spec.get("default_value"),
                    "choices": spec.get("choices", []),
                    "validation_rules": spec.get("validation_rules", {}),
                    "ui_config": spec.get("ui_config", {}),
                    "is_active": True,
                    "updated_by": user,
                    "created_by": user,
                },
            )

        if form.status != Form.PublicationStatus.PUBLISHED:
            form.publish()
        form.sync_schema()
        return form

    def _ensure_recipient(self, form, user):
        existing_default = FormRecipient.objects.filter(
            form=form, is_default=True, is_active=True
        ).first()
        if existing_default:
            return existing_default
        recipient, _ = FormRecipient.objects.update_or_create(
            form=form,
            email=DEMO_EMAIL,
            recipient_type=FormRecipient.RecipientType.TO,
            channel=FormRecipient.ChannelType.SMTP,
            defaults={
                "name": "Demo Empfaenger",
                "is_default": True,
                "is_active": True,
                "config": {"source": "seed_demo_data"},
                "created_by": user,
                "updated_by": user,
            },
        )
        return recipient

    def _ensure_schedule(self, form, user, *, force_due: bool):
        now = timezone.now()
        schedule, _ = FormSchedule.objects.update_or_create(
            form=form,
            name=DEMO_SCHEDULE_NAME,
            defaults={
                "trigger_type": FormSchedule.TriggerType.SCHEDULED,
                "status": FormSchedule.ScheduleStatus.ACTIVE,
                "timezone": "Europe/Berlin",
                "cron_expression": "daily 08:00",
                "start_at": None,
                "end_at": None,
                "next_run_at": now - timedelta(minutes=1) if force_due else now + timedelta(days=1),
                "last_run_at": None,
                "is_active": True,
                "config": {
                    "frequency": "daily",
                    "weekday": 0,
                    "run_time": "08:00",
                    "source": "seed_demo_data",
                },
                "created_by": user,
                "updated_by": user,
            },
        )
        return schedule

    def _ensure_approved_entry(self, form, bewohner, user, *, fresh: bool):
        entry = (
            None
            if fresh
            else FormEntry.objects.filter(form=form, bewohner=bewohner)
            .exclude(status=FormEntry.EntryStatus.DELETED)
            .order_by("-created_at")
            .first()
        )
        payload = {
            "datum": timezone.localdate().isoformat(),
            "pkz": "PKZ-DEMO-001",
            "grund": "routine",
            "bericht": "Demo-Eintrag fuer den professionellen Testlauf. Dieser Eintrag ist freigegeben und kann geplant versendet werden.",
            "rueckmeldung_erforderlich": True,
        }
        if entry is None:
            entry = FormEntry.objects.create(
                form=form,
                bewohner=bewohner,
                status=FormEntry.EntryStatus.APPROVED,
                form_snapshot=form.schema or form.build_schema(),
                data=payload,
                validation_errors={},
                submitted_at=timezone.now(),
                created_by=user,
                updated_by=user,
            )
        else:
            entry.form_snapshot = form.schema or form.build_schema()
            entry.data = payload
            if entry.status not in (
                FormEntry.EntryStatus.READY_TO_SEND,
                FormEntry.EntryStatus.ARCHIVED,
            ):
                entry.status = FormEntry.EntryStatus.APPROVED
            entry.submitted_at = entry.submitted_at or timezone.now()
            entry.updated_by = user
            entry.save(
                update_fields=[
                    "form_snapshot",
                    "data",
                    "status",
                    "submitted_at",
                    "updated_by",
                    "updated_at",
                ]
            )
        AuditLog.objects.create(
            actor=user,
            event_type=AuditLog.EventType.STATUS_CHANGED,
            target_model="FormEntry",
            target_id=entry.pk,
            bewohner=bewohner,
            form=form,
            form_entry=entry,
            message="Demo-Eintrag wurde fuer den Testlauf freigegeben.",
            metadata={"source": "seed_demo_data"},
        )
        return entry

    def _ensure_demo_pdf(self, entry, user):
        existing = (
            PDFDocument.objects.filter(
                form_entry=entry, status=PDFDocument.GenerationStatus.GENERATED
            )
            .order_by("-created_at")
            .first()
        )
        if existing:
            path = get_private_document_root() / existing.storage_key
            if path.exists():
                return existing
        now = timezone.now()
        sha256 = hashlib.sha256(DEMO_PDF_BYTES).hexdigest()
        storage_key = f"pdf_documents/{entry.pk}/demo/demo_{sha256[:12]}.pdf"
        target_path = Path(get_private_document_root() / storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(DEMO_PDF_BYTES)
        pdf_document, _ = PDFDocument.objects.update_or_create(
            form_entry=entry,
            storage_key=storage_key,
            defaults={
                "form": entry.form,
                "bewohner": entry.bewohner,
                "document_kind": PDFDocument.DocumentKind.REVIEW,
                "status": PDFDocument.GenerationStatus.GENERATED,
                "original_filename": f"demo_{entry.form.key}_{entry.public_id}.pdf",
                "content_type": "application/pdf",
                "file_size": len(DEMO_PDF_BYTES),
                "sha256": sha256,
                "page_count": 1,
                "generated_at": now,
                "access_policy": {
                    "private": True,
                    "source": "seed_demo_data",
                    "download_requires_permission": True,
                },
                "created_by": user,
                "updated_by": user,
            },
        )
        AuditLog.objects.create(
            actor=user,
            event_type=AuditLog.EventType.PDF_RENDERED,
            target_model="PDFDocument",
            target_id=pdf_document.pk,
            bewohner=entry.bewohner,
            form=entry.form,
            form_entry=entry,
            message="Demo-PDF wurde privat erzeugt.",
            metadata={"source": "seed_demo_data", "sha256": sha256},
        )
        return pdf_document
