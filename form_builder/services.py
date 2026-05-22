from __future__ import annotations

import base64
import hashlib
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from . import pdf_services
from .attachment_models import FormEntryAttachment, detect_content_type, validate_uploaded_file
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

generate_entry_pdf_document = pdf_services.generate_entry_pdf_document
get_latest_generated_pdf_document = pdf_services.get_latest_generated_pdf_document

FIELD_WIDGETS = {
    Field.FieldType.TEXTAREA: forms.Textarea(attrs={"rows": 4}),
    Field.FieldType.DATE: forms.DateInput(attrs={"type": "date"}),
    Field.FieldType.DATETIME: forms.DateTimeInput(attrs={"type": "datetime-local"}),
}
EDITABLE_ATTACHMENT_STATUSES = {
    FormEntry.EntryStatus.DRAFT,
    FormEntry.EntryStatus.REJECTED,
}


class DynamicEntryForm(forms.Form):
    def __init__(
        self,
        *args,
        schema,
        bewohner_queryset=None,
        include_bewohner=False,
        existing_attachment_keys=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.schema = schema
        existing_attachment_keys = existing_attachment_keys or set()

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
            key = field_definition["key"]
            self.fields[key] = build_form_field(
                field_definition,
                has_existing_attachment=key in existing_attachment_keys,
            )

    @property
    def sectioned_bound_field_groups(self) -> list[dict]:
        """Return BoundFields grouped by schema sections while preserving flat fallback."""
        sections = self.schema.get("sections") or []
        grouped_keys: set[str] = set()
        groups: list[dict] = []

        for section in sections:
            section_keys = section.get("field_keys") or [
                field_definition.get("key")
                for field_definition in section.get("fields", [])
                if field_definition.get("key")
            ]
            bound_fields = []
            for key in section_keys:
                if key in self.fields:
                    bound_fields.append(self[key])
                    grouped_keys.add(key)
            if bound_fields:
                groups.append({"section": section, "fields": bound_fields})

        unsectioned_fields = [field for field in self if field.name not in grouped_keys]
        if unsectioned_fields:
            groups.append({"section": None, "fields": unsectioned_fields})

        return groups


def get_form_schema(form_definition: Form) -> dict:
    schema = deepcopy(form_definition.schema or {})
    if not schema.get("fields"):
        schema = form_definition.build_schema()
    return schema


def _active_attachment_keys(form_entry: FormEntry) -> set[str]:
    if not form_entry.pk:
        return set()
    return set(
        FormEntryAttachment.objects.filter(entry=form_entry, deleted_at__isnull=True).values_list(
            "field_key", flat=True
        )
    )


def build_entry_form(
    form_definition: Form,
    *,
    data=None,
    files=None,
    initial=None,
    include_bewohner=False,
) -> DynamicEntryForm:
    return DynamicEntryForm(
        data=data,
        files=files,
        initial=initial,
        schema=get_form_schema(form_definition),
        include_bewohner=include_bewohner,
    )


def build_entry_form_for_entry(form_entry: FormEntry, *, data=None, files=None) -> DynamicEntryForm:
    initial = _initial_entry_data(form_entry)
    return DynamicEntryForm(
        data=data,
        files=files,
        initial=initial,
        schema=form_entry.form_snapshot or get_form_schema(form_entry.form),
        include_bewohner=False,
        existing_attachment_keys=_active_attachment_keys(form_entry),
    )


def _initial_entry_data(form_entry: FormEntry) -> dict:
    initial = dict(form_entry.data or {})
    for key, value in list(initial.items()):
        if isinstance(value, dict) and value.get("type") == "signature":
            data_url = get_signature_data_url(value)
            if data_url:
                initial[key] = data_url
    return initial


def _file_widget_attrs(field_definition: dict) -> dict:
    rules = field_definition.get("validation_rules") or {}
    ui_config = field_definition.get("ui_config") or {}
    attrs = {}
    allowed = rules.get("allowed_content_types") or rules.get("content_types") or []
    accept = ui_config.get("accept") or rules.get("accept")
    if not accept and allowed:
        if all(str(item).startswith("image/") for item in allowed):
            accept = "image/*"
        else:
            accept = ",".join(str(item) for item in allowed)
    if not accept:
        accept = "image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt"
    attrs["accept"] = accept
    capture = ui_config.get("capture") or rules.get("capture")
    if capture:
        attrs["capture"] = capture if capture is not True else "environment"
    elif accept == "image/*":
        attrs["capture"] = "environment"
    return attrs


def build_form_field(
    field_definition: dict, *, has_existing_attachment: bool = False
) -> forms.Field:
    field_type = field_definition["field_type"]
    required = field_definition.get("required", False)
    label = field_definition.get("label", field_definition["key"])
    help_text = field_definition.get("help_text", "")
    initial = field_definition.get("default_value")
    placeholder = field_definition.get("placeholder", "")
    validation_rules = field_definition.get("validation_rules") or {}
    ui_config = field_definition.get("ui_config") or {}
    widget = FIELD_WIDGETS.get(field_type)

    common_kwargs = {
        "required": required,
        "label": label,
        "help_text": help_text,
        "initial": initial,
    }
    if ui_config.get("widget") == "signature":
        common_kwargs["widget"] = forms.HiddenInput(
            attrs={
                "class": "signature-value",
                "data-signature-field": "1",
                "data-signature-label": label,
            }
        )
        return forms.CharField(**common_kwargs)
    if widget:
        common_kwargs["widget"] = widget
    if placeholder and "widget" in common_kwargs:
        common_kwargs["widget"].attrs.setdefault("placeholder", placeholder)

    if field_type == Field.FieldType.TEXT:
        max_length = validation_rules.get("max_length")
        min_length = validation_rules.get("min_length")
        regex = validation_rules.get("regex")
        validators = []
        if regex:
            from django.core.validators import RegexValidator

            validators.append(
                RegexValidator(
                    regex=regex,
                    message=validation_rules.get(
                        "regex_message", "Bitte gueltiges Format eingeben."
                    ),
                )
            )
        return forms.CharField(
            max_length=max_length,
            min_length=min_length,
            validators=validators,
            **common_kwargs,
        )
    if field_type == Field.FieldType.TEXTAREA:
        return forms.CharField(
            max_length=validation_rules.get("max_length"),
            min_length=validation_rules.get("min_length"),
            **common_kwargs,
        )
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
        help_parts = [help_text] if help_text else []
        rules = field_definition.get("validation_rules") or {}
        max_size_mb = rules.get("max_size_mb") or 10
        help_parts.append(f"Maximale Dateigroesse: {max_size_mb} MB.")
        return forms.FileField(
            required=bool(required and not has_existing_attachment),
            label=label,
            help_text=" ".join(help_parts),
            widget=forms.ClearableFileInput(attrs=_file_widget_attrs(field_definition)),
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
    uploaded_files=None,
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
        persist_entry_attachments_and_signatures(
            form_entry=form_entry,
            cleaned_data=cleaned_data,
            uploaded_files=uploaded_files,
            schema=schema,
            user=user,
        )
    return form_entry


def save_draft_from_validated(
    *, form_entry: FormEntry, cleaned_data: dict, user, uploaded_files=None
) -> FormEntry:
    schema = form_entry.form_snapshot or get_form_schema(form_entry.form)
    form_entry.data = serialize_entry_data(cleaned_data, schema, existing_data=form_entry.data)
    form_entry.validation_errors = {}
    form_entry.status = FormEntry.EntryStatus.DRAFT
    form_entry.updated_by = user
    form_entry.save(
        update_fields=["data", "validation_errors", "status", "updated_by", "updated_at"]
    )
    persist_entry_attachments_and_signatures(
        form_entry=form_entry,
        cleaned_data=cleaned_data,
        uploaded_files=uploaded_files,
        schema=schema,
        user=user,
    )
    return form_entry


def validate_draft(
    form_entry: FormEntry, cleaned_data: dict, user, uploaded_files=None
) -> FormEntry:
    schema = form_entry.form_snapshot or get_form_schema(form_entry.form)
    form_entry.data = serialize_entry_data(cleaned_data, schema, existing_data=form_entry.data)
    form_entry.validation_errors = {}
    form_entry.updated_by = user
    form_entry.save(update_fields=["data", "validation_errors", "updated_by", "updated_at"])
    persist_entry_attachments_and_signatures(
        form_entry=form_entry,
        cleaned_data=cleaned_data,
        uploaded_files=uploaded_files,
        schema=schema,
        user=user,
    )
    return form_entry


def submit_draft_for_review(
    form_entry: FormEntry, cleaned_data: dict, user, uploaded_files=None
) -> FormEntry:
    if form_entry.status not in (
        FormEntry.EntryStatus.DRAFT,
        FormEntry.EntryStatus.REJECTED,
    ):
        raise ValidationError(
            "Nur Entwuerfe oder zurueckgewiesene Eintraege koennen in Review gesetzt werden."
        )

    schema = form_entry.form_snapshot or get_form_schema(form_entry.form)
    form_entry.data = serialize_entry_data(cleaned_data, schema, existing_data=form_entry.data)
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
    persist_entry_attachments_and_signatures(
        form_entry=form_entry,
        cleaned_data=cleaned_data,
        uploaded_files=uploaded_files,
        schema=schema,
        user=user,
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


def _format_recipient_template(template: str, form_entry: FormEntry) -> str:
    if not template:
        return ""
    data = form_entry.data or {}
    values = {
        "form": form_entry.form.title,
        "name": data.get("name") or getattr(form_entry.bewohner, "last_name", ""),
        "vorname": data.get("vorname") or getattr(form_entry.bewohner, "first_name", ""),
        "pkz": data.get("pkz", ""),
        "aktenzeichen": data.get("aktenzeichen", ""),
    }
    try:
        return template.format(**values)
    except Exception:
        return template


def get_latest_final_pdf_document(form_entry: FormEntry) -> PDFDocument | None:
    return (
        PDFDocument.objects.filter(
            form_entry=form_entry,
            document_kind=PDFDocument.DocumentKind.FINAL,
            status=PDFDocument.GenerationStatus.GENERATED,
        )
        .order_by("-generated_at", "-created_at")
        .first()
    )


def get_or_create_final_pdf_document(*, form_entry: FormEntry, user) -> PDFDocument:
    pdf_document = get_latest_final_pdf_document(form_entry)
    if pdf_document:
        return pdf_document
    return generate_entry_pdf_document(
        form_entry=form_entry,
        user=user,
        document_kind=PDFDocument.DocumentKind.FINAL,
    )


def queue_entry_for_delivery(*, form_entry: FormEntry, user) -> list[OutboxItem]:
    if form_entry.status != FormEntry.EntryStatus.APPROVED:
        raise ValidationError(
            "Nur freigegebene Eintraege koennen in den Ausgangskorb gestellt werden."
        )

    if OutboxItem.objects.filter(
        form_entry=form_entry, status=OutboxItem.DeliveryStatus.PENDING
    ).exists():
        raise ValidationError("Fuer diesen Eintrag gibt es bereits offene Versandpositionen.")

    recipients = list(
        FormRecipient.objects.filter(
            form=form_entry.form, is_active=True, is_default=True
        ).order_by("recipient_type", "email")
    )
    if not recipients:
        recipients = list(
            FormRecipient.objects.filter(form=form_entry.form, is_active=True).order_by(
                "recipient_type", "email"
            )
        )
    if not recipients:
        raise ValidationError("Fuer dieses Formular ist kein aktives E-Mail-Ziel hinterlegt.")

    pdf_document = get_or_create_final_pdf_document(form_entry=form_entry, user=user)

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
                subject=_format_recipient_template(recipient.subject_template, form_entry)
                or f"{form_entry.form.title} - {form_entry.bewohner}",
                body=_format_recipient_template(recipient.body_template, form_entry)
                or "Anbei erhalten Sie das Formular als PDF.",
                payload={
                    "form_entry_id": str(form_entry.pk),
                    "recipient_id": str(recipient.pk),
                    "queued_by": str(user.pk) if user else None,
                    "pdf_document_id": str(pdf_document.pk),
                    "pdf_sha256": pdf_document.sha256,
                    "source": "manual_send",
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
            message="Formulareintrag wurde zum Versand vorgemerkt.",
            metadata={
                "new_status": FormEntry.EntryStatus.READY_TO_SEND,
                "outbox_item_count": len(created_items),
                "pdf_document_id": str(pdf_document.pk),
            },
        )

    return created_items


def serialize_entry_data(
    cleaned_data: dict, schema: dict, *, existing_data: dict | None = None
) -> dict:
    payload = {}
    existing_data = existing_data or {}
    field_definitions = {
        field_definition["key"]: field_definition for field_definition in schema.get("fields", [])
    }
    for key, field_definition in field_definitions.items():
        if key not in cleaned_data:
            if key in existing_data:
                payload[key] = existing_data[key]
            continue
        if field_definition.get("field_type") == Field.FieldType.FILE:
            if key in existing_data:
                payload[key] = existing_data[key]
            continue
        value = cleaned_data.get(key)
        if _is_signature_field(field_definition) and value in (None, "") and key in existing_data:
            payload[key] = existing_data[key]
            continue
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


def _is_signature_field(field_definition: dict) -> bool:
    return (field_definition.get("ui_config") or {}).get("widget") == "signature"


def _field_model_for(form_entry: FormEntry, field_definition: dict):
    field_id = field_definition.get("id")
    if field_id:
        try:
            return Field.objects.get(pk=field_id, form=form_entry.form)
        except Field.DoesNotExist:
            return None
    return Field.objects.filter(form=form_entry.form, key=field_definition.get("key")).first()


def _uploaded_file_for(uploaded_files, key: str):
    if not uploaded_files:
        return None
    if hasattr(uploaded_files, "get"):
        return uploaded_files.get(key)
    return None


def _replace_existing_attachments(
    *, form_entry: FormEntry, field_key: str, user, kind: str
) -> None:
    for attachment in FormEntryAttachment.objects.filter(
        entry=form_entry,
        field_key=field_key,
        kind=kind,
        deleted_at__isnull=True,
    ):
        attachment.mark_deleted(user=user)


def _attachment_payload(attachment: FormEntryAttachment) -> dict:
    return {
        "type": attachment.kind,
        "attachment_id": str(attachment.pk),
        "filename": attachment.original_filename,
        "content_type": attachment.content_type,
        "size": attachment.size,
        "sha256": attachment.sha256,
        "uploaded_at": attachment.created_at.isoformat() if attachment.created_at else "",
    }


def persist_entry_attachments_and_signatures(
    *,
    form_entry: FormEntry,
    cleaned_data: dict,
    uploaded_files=None,
    schema: dict | None = None,
    user=None,
) -> None:
    if form_entry.status not in EDITABLE_ATTACHMENT_STATUSES:
        return
    schema = schema or form_entry.form_snapshot or get_form_schema(form_entry.form)
    changed = False
    data = dict(form_entry.data or {})
    for field_definition in schema.get("fields", []):
        key = field_definition.get("key")
        if not key:
            continue
        if field_definition.get("field_type") == Field.FieldType.FILE:
            uploaded_file = _uploaded_file_for(uploaded_files, key)
            if not uploaded_file:
                continue
            validate_uploaded_file(uploaded_file, field_definition=field_definition)
            _replace_existing_attachments(
                form_entry=form_entry,
                field_key=key,
                user=user,
                kind=FormEntryAttachment.AttachmentKind.FILE,
            )
            sha256 = hashlib.sha256(uploaded_file.read()).hexdigest()
            uploaded_file.seek(0)
            attachment = FormEntryAttachment.objects.create(
                entry=form_entry,
                field=_field_model_for(form_entry, field_definition),
                field_key=key,
                kind=FormEntryAttachment.AttachmentKind.FILE,
                original_filename=getattr(uploaded_file, "name", "attachment.bin")[:255],
                file=uploaded_file,
                content_type=detect_content_type(uploaded_file),
                size=int(getattr(uploaded_file, "size", 0) or 0),
                sha256=sha256,
                uploaded_by=user,
                metadata={"source": "dynamic_form_field"},
            )
            data[key] = _attachment_payload(attachment)
            changed = True
            _audit_attachment(
                actor=user,
                event_type=AuditLog.EventType.CREATED,
                form_entry=form_entry,
                attachment=attachment,
                message="Dateianhang wurde hochgeladen.",
            )
        elif _is_signature_field(field_definition):
            raw_value = cleaned_data.get(key)
            if (
                not raw_value
                or isinstance(raw_value, dict)
                or not str(raw_value).startswith("data:image/png;base64,")
            ):
                continue
            attachment = _store_signature_attachment(
                form_entry=form_entry,
                field_definition=field_definition,
                field_key=key,
                data_url=str(raw_value),
                user=user,
            )
            if attachment:
                signer = getattr(user, "username", "") if user else "-"
                signed_at = attachment.signed_at.isoformat() if attachment.signed_at else ""
                data[key] = (
                    f"Unterschrieben durch {signer} am {signed_at[:16]} "
                    f"(SHA-256 {attachment.signature_hash[:12]}...)"
                )
                changed = True
    if changed:
        FormEntry.objects.filter(pk=form_entry.pk).update(data=data, updated_at=timezone.now())
        form_entry.data = data


def _store_signature_attachment(
    *,
    form_entry: FormEntry,
    field_definition: dict,
    field_key: str,
    data_url: str,
    user=None,
) -> FormEntryAttachment | None:
    if not data_url.startswith("data:image/png;base64,"):
        raise ValidationError("Unterschrift muss als PNG-Daten gespeichert werden.")
    try:
        payload = data_url.split(",", 1)[1]
        binary = base64.b64decode(payload)
    except Exception as exc:
        raise ValidationError("Unterschrift konnte nicht gelesen werden.") from exc
    if not binary:
        return None
    signature_hash = hashlib.sha256(binary).hexdigest()
    existing = FormEntryAttachment.objects.filter(
        entry=form_entry,
        field_key=field_key,
        kind=FormEntryAttachment.AttachmentKind.SIGNATURE,
        signature_hash=signature_hash,
        deleted_at__isnull=True,
    ).first()
    if existing:
        return existing
    _replace_existing_attachments(
        form_entry=form_entry,
        field_key=field_key,
        user=user,
        kind=FormEntryAttachment.AttachmentKind.SIGNATURE,
    )
    content = ContentFile(binary, name=f"signature_{field_key}.png")
    validate_uploaded_file(content, field_definition=field_definition, signature=True)
    now = timezone.now()
    attachment = FormEntryAttachment.objects.create(
        entry=form_entry,
        field=_field_model_for(form_entry, field_definition),
        field_key=field_key,
        kind=FormEntryAttachment.AttachmentKind.SIGNATURE,
        original_filename=f"signature_{field_key}.png",
        file=content,
        content_type="image/png",
        size=len(binary),
        sha256=signature_hash,
        uploaded_by=user,
        signed_by=user,
        signed_at=now,
        signature_hash=signature_hash,
        metadata={
            "source": "signature_pad",
            "field_label": field_definition.get("label", field_key),
        },
    )
    _audit_attachment(
        actor=user,
        event_type=AuditLog.EventType.CREATED,
        form_entry=form_entry,
        attachment=attachment,
        message="Unterschrift wurde gespeichert.",
    )
    return attachment


def _audit_attachment(
    *, actor, event_type, form_entry: FormEntry, attachment: FormEntryAttachment, message: str
) -> None:
    AuditLog.objects.create(
        actor=actor,
        event_type=event_type,
        target_model="FormEntryAttachment",
        target_id=attachment.pk,
        bewohner=form_entry.bewohner,
        form=form_entry.form,
        form_entry=form_entry,
        message=message,
        metadata={
            "attachment_id": str(attachment.pk),
            "field_key": attachment.field_key,
            "kind": attachment.kind,
            "sha256": attachment.sha256,
        },
    )


def get_entry_attachments(form_entry: FormEntry):
    return FormEntryAttachment.objects.filter(entry=form_entry, deleted_at__isnull=True).order_by(
        "field_key", "created_at"
    )


def get_signature_data_url(value: dict | str | None) -> str:
    if isinstance(value, str) and value.startswith("data:image/"):
        return value
    if not isinstance(value, dict):
        return ""
    attachment_id = value.get("attachment_id")
    if not attachment_id:
        return ""
    try:
        attachment = FormEntryAttachment.objects.get(pk=attachment_id, deleted_at__isnull=True)
        with attachment.file.open("rb") as fh:
            payload = base64.b64encode(fh.read()).decode("ascii")
        return f"data:{attachment.content_type};base64,{payload}"
    except Exception:
        return ""
