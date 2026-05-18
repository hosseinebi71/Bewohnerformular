from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AuditLog,
    Bewohner,
    Field,
    Form,
    FormEntry,
    FormRecipient,
    OutboxItem,
    PDFDocument,
)

FIELD_WIDGETS = {
    Field.FieldType.TEXTAREA: forms.Textarea(attrs={"rows": 4}),
    Field.FieldType.DATE: forms.DateInput(attrs={"type": "date"}),
    Field.FieldType.DATETIME: forms.DateTimeInput(attrs={"type": "datetime-local"}),
}


class DynamicEntryForm(forms.Form):
    def __init__(
        self,
        *args,
        schema,
        bewohner_queryset=None,
        include_bewohner=False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.schema = schema

        if include_bewohner:
            queryset = bewohner_queryset or Bewohner.objects.order_by(
                "last_name",
                "first_name",
                "resident_number",
            )
            self.fields["bewohner"] = forms.ModelChoiceField(
                queryset=queryset,
                label="Bewohner",
                help_text=(
                    "Lokale Test-Referenz. Spaeter wird hier eine externe Bewohner-App angebunden."
                ),
            )

        for field_definition in schema.get("fields", []):
            self.fields[field_definition["key"]] = build_form_field(field_definition)


def get_form_schema(form_definition: Form) -> dict:
    schema = deepcopy(form_definition.schema or {})
    if not schema.get("fields"):
        schema = form_definition.build_schema()
    return schema


def build_entry_form(
    form_definition: Form,
    *,
    data=None,
    initial=None,
    include_bewohner=False,
) -> DynamicEntryForm:
    return DynamicEntryForm(
        data=data,
        initial=initial,
        schema=get_form_schema(form_definition),
        include_bewohner=include_bewohner,
    )


def build_entry_form_for_entry(form_entry: FormEntry, *, data=None) -> DynamicEntryForm:
    initial = form_entry.data or {}
    return DynamicEntryForm(
        data=data,
        initial=initial,
        schema=form_entry.form_snapshot or get_form_schema(form_entry.form),
        include_bewohner=False,
    )


def build_form_field(field_definition: dict) -> forms.Field:
    field_type = field_definition["field_type"]
    required = field_definition.get("required", False)
    label = field_definition.get("label", field_definition["key"])
    help_text = field_definition.get("help_text", "")
    initial = field_definition.get("default_value")
    placeholder = field_definition.get("placeholder", "")
    validation_rules = field_definition.get("validation_rules") or {}
    widget = FIELD_WIDGETS.get(field_type)

    common_kwargs = {
        "required": required,
        "label": label,
        "help_text": help_text,
        "initial": initial,
    }
    if widget:
        common_kwargs["widget"] = widget
    if placeholder and "widget" in common_kwargs:
        common_kwargs["widget"].attrs.setdefault("placeholder", placeholder)

    if field_type == Field.FieldType.TEXT:
        return forms.CharField(**common_kwargs)
    if field_type == Field.FieldType.TEXTAREA:
        return forms.CharField(**common_kwargs)
    if field_type == Field.FieldType.INTEGER:
        return forms.IntegerField(
            min_value=validation_rules.get("min_value"),
            max_value=validation_rules.get("max_value"),
            **common_kwargs,
        )
    if field_type == Field.FieldType.DECIMAL:
        return forms.DecimalField(
            min_value=validation_rules.get("min_value"),
            max_value=validation_rules.get("max_value"),
            decimal_places=validation_rules.get("decimal_places", 2),
            max_digits=validation_rules.get("max_digits", 12),
            **common_kwargs,
        )
    if field_type == Field.FieldType.DATE:
        return forms.DateField(**common_kwargs)
    if field_type == Field.FieldType.DATETIME:
        return forms.DateTimeField(**common_kwargs)
    if field_type == Field.FieldType.BOOLEAN:
        return forms.BooleanField(
            required=required, label=label, help_text=help_text, initial=initial
        )
    if field_type in (Field.FieldType.SELECT, Field.FieldType.RADIO):
        choices = normalize_choices(field_definition.get("choices", []))
        if field_type == Field.FieldType.RADIO:
            common_kwargs["widget"] = forms.RadioSelect
        return forms.ChoiceField(choices=choices, **common_kwargs)
    if field_type == Field.FieldType.MULTISELECT:
        return forms.MultipleChoiceField(
            choices=normalize_choices(field_definition.get("choices", [])),
            required=required,
            label=label,
            help_text=help_text,
            initial=initial,
        )
    if field_type == Field.FieldType.EMAIL:
        return forms.EmailField(**common_kwargs)
    if field_type == Field.FieldType.PHONE:
        return forms.CharField(**common_kwargs)
    if field_type == Field.FieldType.FILE:
        return forms.CharField(
            required=False,
            label=label,
            help_text="Datei-Uploads sind in diesem lokalen Draft-Flow noch nicht aktiviert.",
            disabled=True,
        )
    return forms.CharField(**common_kwargs)


def normalize_choices(choices: list[dict]) -> list[tuple[str, str]]:
    return [(choice["value"], choice["label"]) for choice in choices]


def _text_value(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def ensure_bewohner_from_entry_payload(*, payload: dict, user) -> Bewohner:
    """Create a resident reference from the form itself.

    The application still stores entries against Bewohner for audit/archive integrity,
    but the user does not have to choose a pre-existing resident while filling a form.
    """
    last_name = _text_value(payload, "name", "nachname", "familienname") or "Unbekannt"
    first_name = _text_value(payload, "vorname", "first_name") or ""
    date_of_birth = (
        payload.get("geb_am") or payload.get("geburtsdatum") or payload.get("date_of_birth") or None
    )
    room_label = _text_value(payload, "zimmer", "room", "raum")
    pkz = _text_value(payload, "pkz", "personalkennzeichen", "aktenzeichen")
    stable_hint = pkz or f"{last_name}-{first_name}-{uuid4().hex[:8]}"
    resident_number = f"FORM-{stable_hint}"[:64]

    bewohner, created = Bewohner.objects.get_or_create(
        resident_number=resident_number,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": date_of_birth or None,
            "room_label": room_label,
            "status": Bewohner.RecordStatus.ACTIVE,
            "notes": "Automatisch aus einem Formularvorgang erzeugte Arbeitsreferenz.",
            "created_by": user,
            "updated_by": user,
        },
    )
    if not created:
        update_fields = []
        if first_name and bewohner.first_name != first_name:
            bewohner.first_name = first_name
            update_fields.append("first_name")
        if last_name and bewohner.last_name != last_name:
            bewohner.last_name = last_name
            update_fields.append("last_name")
        if date_of_birth and not bewohner.date_of_birth:
            bewohner.date_of_birth = date_of_birth
            update_fields.append("date_of_birth")
        if room_label and bewohner.room_label != room_label:
            bewohner.room_label = room_label
            update_fields.append("room_label")
        bewohner.updated_by = user
        update_fields.extend(["updated_by", "updated_at"])
        bewohner.save(update_fields=update_fields)
    return bewohner


def create_form_entry_from_validated(
    *,
    form_definition: Form,
    bewohner: Bewohner | None = None,
    cleaned_data: dict,
    user,
) -> FormEntry:
    schema = get_form_schema(form_definition)
    explicit_bewohner = cleaned_data.get("bewohner")
    payload = serialize_entry_data(cleaned_data, schema)
    bewohner = (
        bewohner
        or explicit_bewohner
        or ensure_bewohner_from_entry_payload(payload=payload, user=user)
    )
    with transaction.atomic():
        form_entry = FormEntry.objects.create(
            form=form_definition,
            bewohner=bewohner,
            status=FormEntry.EntryStatus.DRAFT,
            form_snapshot=schema,
            data=payload,
            validation_errors={},
            created_by=user,
            updated_by=user,
        )
    return form_entry


def save_draft_from_validated(*, form_entry: FormEntry, cleaned_data: dict, user) -> FormEntry:
    schema = form_entry.form_snapshot or get_form_schema(form_entry.form)
    form_entry.data = serialize_entry_data(cleaned_data, schema)
    form_entry.validation_errors = {}
    form_entry.status = FormEntry.EntryStatus.DRAFT
    form_entry.updated_by = user
    form_entry.save(
        update_fields=["data", "validation_errors", "status", "updated_by", "updated_at"]
    )
    return form_entry


def validate_draft(form_entry: FormEntry, cleaned_data: dict, user) -> FormEntry:
    schema = form_entry.form_snapshot or get_form_schema(form_entry.form)
    form_entry.data = serialize_entry_data(cleaned_data, schema)
    form_entry.validation_errors = {}
    form_entry.updated_by = user
    form_entry.save(update_fields=["data", "validation_errors", "updated_by", "updated_at"])
    return form_entry


def submit_draft_for_review(form_entry: FormEntry, cleaned_data: dict, user) -> FormEntry:
    if form_entry.status not in (
        FormEntry.EntryStatus.DRAFT,
        FormEntry.EntryStatus.REJECTED,
    ):
        raise ValidationError(
            "Nur Entwuerfe oder zurueckgewiesene Eintraege koennen in Review gesetzt werden."
        )

    schema = form_entry.form_snapshot or get_form_schema(form_entry.form)
    form_entry.data = serialize_entry_data(cleaned_data, schema)
    form_entry.validation_errors = {}
    form_entry.status = FormEntry.EntryStatus.IN_REVIEW
    form_entry.submitted_at = timezone.now()
    form_entry.updated_by = user
    form_entry.save(
        update_fields=[
            "data",
            "validation_errors",
            "status",
            "submitted_at",
            "updated_by",
            "updated_at",
        ]
    )
    return form_entry


def _create_audit_log(
    *, actor, event_type, form_entry: FormEntry, message: str, metadata: dict | None = None
) -> None:
    AuditLog.objects.create(
        actor=actor,
        event_type=event_type,
        target_model="FormEntry",
        target_id=form_entry.pk,
        bewohner=form_entry.bewohner,
        form=form_entry.form,
        form_entry=form_entry,
        message=message,
        metadata=metadata or {},
    )


def approve_entry_for_sending(*, form_entry: FormEntry, user) -> FormEntry:
    if form_entry.status != FormEntry.EntryStatus.IN_REVIEW:
        raise ValidationError("Nur Eintraege in Pruefung koennen freigegeben werden.")

    form_entry.status = FormEntry.EntryStatus.APPROVED
    form_entry.updated_by = user
    form_entry.save(update_fields=["status", "updated_by", "updated_at"])
    _create_audit_log(
        actor=user,
        event_type=AuditLog.EventType.STATUS_CHANGED,
        form_entry=form_entry,
        message="Formulareintrag wurde freigegeben.",
        metadata={"new_status": FormEntry.EntryStatus.APPROVED},
    )
    return form_entry


def reject_entry_for_correction(*, form_entry: FormEntry, user, reason: str = "") -> FormEntry:
    if form_entry.status != FormEntry.EntryStatus.IN_REVIEW:
        raise ValidationError("Nur Eintraege in Pruefung koennen zurueckgewiesen werden.")

    form_entry.status = FormEntry.EntryStatus.REJECTED
    form_entry.updated_by = user
    form_entry.validation_errors = {"review": reason} if reason else {}
    form_entry.save(update_fields=["status", "updated_by", "validation_errors", "updated_at"])
    _create_audit_log(
        actor=user,
        event_type=AuditLog.EventType.STATUS_CHANGED,
        form_entry=form_entry,
        message="Formulareintrag wurde zur Nachbearbeitung zurueckgewiesen.",
        metadata={"new_status": FormEntry.EntryStatus.REJECTED, "reason": reason},
    )
    return form_entry


def get_latest_generated_pdf_document(form_entry: FormEntry) -> PDFDocument | None:
    return (
        PDFDocument.objects.filter(
            form_entry=form_entry,
            status=PDFDocument.GenerationStatus.GENERATED,
        )
        .order_by("-generated_at", "-created_at")
        .first()
    )


def queue_entry_for_delivery(*, form_entry: FormEntry, user) -> list[OutboxItem]:
    if form_entry.status != FormEntry.EntryStatus.APPROVED:
        raise ValidationError(
            "Nur freigegebene Eintraege koennen in den Ausgangskorb gestellt werden."
        )

    pdf_document = get_latest_generated_pdf_document(form_entry)
    if not pdf_document:
        raise ValidationError(
            "Bitte zuerst eine PDF-Vorschau erzeugen, bevor der Eintrag in den Ausgangskorb gestellt wird."
        )

    recipients = list(
        FormRecipient.objects.filter(
            form=form_entry.form,
            is_active=True,
            is_default=True,
        ).order_by("recipient_type", "email")
    )
    if not recipients:
        raise ValidationError(
            "Fuer dieses Formular ist kein aktiver Standard-Empfaenger hinterlegt."
        )

    created_items: list[OutboxItem] = []
    with transaction.atomic():
        form_entry.status = FormEntry.EntryStatus.READY_TO_SEND
        form_entry.updated_by = user
        form_entry.save(update_fields=["status", "updated_by", "updated_at"])

        for recipient in recipients:
            item = OutboxItem.objects.create(
                form=form_entry.form,
                form_entry=form_entry,
                bewohner=form_entry.bewohner,
                recipient=recipient,
                pdf_document=pdf_document,
                status=OutboxItem.DeliveryStatus.PENDING,
                subject=f"{form_entry.form.title} - {form_entry.bewohner}",
                body="Dieses Formular wurde zur sicheren Verarbeitung in den Ausgangskorb gestellt.",
                payload={
                    "form_entry_id": str(form_entry.pk),
                    "recipient_id": str(recipient.pk),
                    "queued_by": str(user.pk) if user else None,
                    "pdf_document_id": str(pdf_document.pk),
                    "pdf_sha256": pdf_document.sha256,
                },
                next_attempt_at=timezone.now(),
                created_by=user,
                updated_by=user,
            )
            created_items.append(item)

        _create_audit_log(
            actor=user,
            event_type=AuditLog.EventType.STATUS_CHANGED,
            form_entry=form_entry,
            message="Formulareintrag wurde in den Ausgangskorb gestellt.",
            metadata={
                "new_status": FormEntry.EntryStatus.READY_TO_SEND,
                "outbox_item_count": len(created_items),
                "pdf_document_id": str(pdf_document.pk),
            },
        )

    return created_items


def serialize_entry_data(cleaned_data: dict, schema: dict) -> dict:
    payload = {}
    schema_keys = {field_definition["key"] for field_definition in schema.get("fields", [])}
    for key, value in cleaned_data.items():
        if key in schema_keys:
            payload[key] = serialize_value(value)
    return payload


def serialize_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    return value
