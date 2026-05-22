from __future__ import annotations

from io import BytesIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, FormEntry
from .qr_context_models import QRFormContext


SAFE_CONTEXT_FIELD_KEYS = {
    "room_label",
    "zimmer",
    "raum",
    "bereich",
    "location",
    "standort",
    "asset",
    "objekt",
}


def build_qr_open_url(request, context: QRFormContext) -> str:
    path = reverse("form_builder:qr_context_open", kwargs={"token": context.token})
    return request.build_absolute_uri(path)


def render_qr_png(data: str) -> bytes:
    import qrcode

    image = qrcode.make(data)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _safe_initial_data(context: QRFormContext) -> dict:
    payload = dict(context.context_payload or {})
    if context.context_key:
        payload.setdefault("qr_context", context.context_key)
    if context.context_type:
        payload.setdefault("qr_context_type", context.context_type)
    if context.bewohner_id:
        payload.setdefault("name", context.bewohner.last_name)
        payload.setdefault("vorname", context.bewohner.first_name)
        payload.setdefault("pkz", context.bewohner.resident_number)
        if context.bewohner.room_label:
            payload.setdefault("room_label", context.bewohner.room_label)
    schema_keys = {field.get("key") for field in (context.form.schema or {}).get("fields", [])}
    allowed = set(schema_keys) | SAFE_CONTEXT_FIELD_KEYS
    return {str(key): value for key, value in payload.items() if str(key) in allowed}


def create_entry_from_qr_context(*, context: QRFormContext, user) -> FormEntry:
    if not context.can_open:
        raise PermissionDenied("Dieser QR-Code ist nicht mehr aktiv.")
    if context.form.status != context.form.PublicationStatus.PUBLISHED:
        raise ValidationError("Das verknuepfte Formular ist nicht veroeffentlicht.")
    if not context.form.schema:
        context.form.sync_schema()
        context.form.refresh_from_db(fields=["schema"])
    bewohner = context.bewohner
    if bewohner is None:
        from .services import ensure_bewohner_from_entry_payload

        bewohner = ensure_bewohner_from_entry_payload(
            payload={
                "name": "QR-Kontext",
                "vorname": context.label[:80] or "Formular",
                "pkz": f"QR-{context.token[:10]}",
                "room_label": context.context_key,
            },
            user=user,
        )
    initial_data = _safe_initial_data(context)
    form_entry = FormEntry.objects.create(
        form=context.form,
        bewohner=bewohner,
        status=FormEntry.EntryStatus.DRAFT,
        form_snapshot=context.form.schema,
        data=initial_data,
        validation_errors={},
        created_by=user,
        updated_by=user,
    )
    context.mark_used()
    AuditLog.objects.create(
        actor=user,
        event_type=AuditLog.EventType.CREATED,
        target_model="FormEntry",
        target_id=form_entry.pk,
        bewohner=bewohner,
        form=context.form,
        form_entry=form_entry,
        message="Formulareintrag wurde aus QR-Kontext erstellt.",
        metadata={
            "qr_context_id": str(context.pk),
            "context_type": context.context_type,
            "context_key": context.context_key,
            "opened_at": timezone.now().isoformat(),
        },
    )
    return form_entry
