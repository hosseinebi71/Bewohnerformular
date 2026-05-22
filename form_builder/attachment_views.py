from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect

from .attachment_models import FormEntryAttachment
from .models import AuditLog, FormEntry
from .permissions import can_edit_entry, can_view_entry, can_view_forms
from .services import EDITABLE_ATTACHMENT_STATUSES
from .views import require_permission


@login_required(login_url="login")
def attachment_download_view(request, attachment_id):
    require_permission(can_view_forms(request.user))
    attachment = get_object_or_404(
        FormEntryAttachment.objects.select_related("entry", "entry__form", "entry__bewohner"),
        pk=attachment_id,
        deleted_at__isnull=True,
    )
    if not can_view_entry(request.user, attachment.entry):
        AuditLog.objects.create(
            actor=request.user,
            event_type=AuditLog.EventType.PERMISSION_DENIED,
            target_model="FormEntryAttachment",
            target_id=attachment.pk,
            bewohner=attachment.entry.bewohner,
            form=attachment.entry.form,
            form_entry=attachment.entry,
            message="Download eines Formular-Anhangs wurde verweigert.",
            metadata={"attachment_id": str(attachment.pk), "field_key": attachment.field_key},
        )
        raise PermissionDenied
    try:
        response = FileResponse(
            attachment.file.open("rb"),
            as_attachment=False,
            filename=attachment.original_filename,
            content_type=attachment.content_type or "application/octet-stream",
        )
    except FileNotFoundError as exc:
        raise Http404("Datei wurde nicht gefunden.") from exc
    AuditLog.objects.create(
        actor=request.user,
        event_type=AuditLog.EventType.DOWNLOAD,
        target_model="FormEntryAttachment",
        target_id=attachment.pk,
        bewohner=attachment.entry.bewohner,
        form=attachment.entry.form,
        form_entry=attachment.entry,
        message="Formular-Anhang wurde heruntergeladen.",
        metadata={
            "attachment_id": str(attachment.pk),
            "field_key": attachment.field_key,
            "kind": attachment.kind,
            "sha256": attachment.sha256,
        },
    )
    return response


@login_required(login_url="login")
def attachment_delete_view(request, attachment_id):
    attachment = get_object_or_404(
        FormEntryAttachment.objects.select_related("entry", "entry__form", "entry__bewohner"),
        pk=attachment_id,
        deleted_at__isnull=True,
    )
    entry = attachment.entry
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=entry.pk)
    if not can_edit_entry(request.user, entry):
        raise PermissionDenied
    if entry.status not in EDITABLE_ATTACHMENT_STATUSES:
        raise ValidationError("Anhaenge koennen nach Review/Freigabe nicht mehr geaendert werden.")
    attachment.mark_deleted(user=request.user)
    data = dict(entry.data or {})
    current_value = data.get(attachment.field_key)
    if (
        isinstance(current_value, dict)
        and current_value.get("attachment_id") == str(attachment.pk)
    ) or not isinstance(current_value, dict):
        data.pop(attachment.field_key, None)
        FormEntry.objects.filter(pk=entry.pk).update(data=data)
    AuditLog.objects.create(
        actor=request.user,
        event_type=AuditLog.EventType.DELETED,
        target_model="FormEntryAttachment",
        target_id=attachment.pk,
        bewohner=entry.bewohner,
        form=entry.form,
        form_entry=entry,
        message="Formular-Anhang wurde geloescht.",
        metadata={
            "attachment_id": str(attachment.pk),
            "field_key": attachment.field_key,
            "kind": attachment.kind,
            "sha256": attachment.sha256,
        },
    )
    messages.success(request, "Anhang wurde entfernt.")
    return redirect("form_builder:entry_edit", entry_id=entry.pk)
