from __future__ import annotations

import hashlib
import mimetypes
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import get_valid_filename

from .models import Field, FormEntry, TimeStampedModel, UUIDPrimaryKeyModel

DEFAULT_ALLOWED_ATTACHMENT_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/plain",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
DEFAULT_MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
SIGNATURE_MAX_SIZE = 2 * 1024 * 1024


def form_entry_attachment_upload_to(instance, filename: str) -> str:
    safe_name = get_valid_filename(os.path.basename(filename or "attachment.bin"))[:180]
    field_key = get_valid_filename(instance.field_key or "field")[:80]
    entry_id = instance.entry_id or "pending"
    return f"private/form_entry_attachments/{entry_id}/{field_key}/{uuid.uuid4().hex}_{safe_name}"


def detect_content_type(uploaded_file) -> str:
    content_type = (getattr(uploaded_file, "content_type", "") or "").split(";", 1)[0].strip()
    if content_type:
        return content_type
    guessed, _encoding = mimetypes.guess_type(getattr(uploaded_file, "name", ""))
    return guessed or "application/octet-stream"


def calculate_sha256(uploaded_file) -> str:
    digest = hashlib.sha256()
    position = None
    if hasattr(uploaded_file, "tell") and hasattr(uploaded_file, "seek"):
        try:
            position = uploaded_file.tell()
            uploaded_file.seek(0)
        except Exception:
            position = None
    for chunk in (
        uploaded_file.chunks() if hasattr(uploaded_file, "chunks") else [uploaded_file.read()]
    ):
        digest.update(chunk)
    if position is not None:
        uploaded_file.seek(position)
    return digest.hexdigest()


def validate_uploaded_file(
    uploaded_file, *, field_definition: dict | None = None, signature: bool = False
) -> None:
    field_definition = field_definition or {}
    rules = field_definition.get("validation_rules") or {}
    filename = getattr(uploaded_file, "name", "Datei")
    size = int(getattr(uploaded_file, "size", 0) or 0)
    max_size = SIGNATURE_MAX_SIZE if signature else int(rules.get("max_size_bytes") or 0)
    if not max_size:
        max_size_mb = rules.get("max_size_mb")
        max_size = (
            int(float(max_size_mb) * 1024 * 1024) if max_size_mb else DEFAULT_MAX_ATTACHMENT_SIZE
        )
    if size > max_size:
        raise ValidationError(
            f"{filename}: Die Datei ist zu gross. Maximal erlaubt sind {max_size // (1024 * 1024)} MB."
        )
    content_type = detect_content_type(uploaded_file)
    if signature:
        allowed_content_types = {"image/png"}
    else:
        configured = rules.get("allowed_content_types") or rules.get("content_types") or []
        allowed_content_types = set(configured or DEFAULT_ALLOWED_ATTACHMENT_CONTENT_TYPES)
    if content_type not in allowed_content_types:
        raise ValidationError(
            f"{filename}: Dateityp {content_type or 'unbekannt'} ist fuer dieses Feld nicht erlaubt."
        )


class FormEntryAttachment(UUIDPrimaryKeyModel, TimeStampedModel):
    class AttachmentKind(models.TextChoices):
        FILE = "file", "Datei"
        SIGNATURE = "signature", "Unterschrift"

    entry = models.ForeignKey(
        FormEntry,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    field = models.ForeignKey(
        Field,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entry_attachments",
    )
    field_key = models.SlugField(max_length=80, db_index=True)
    kind = models.CharField(
        max_length=24, choices=AttachmentKind.choices, default=AttachmentKind.FILE
    )
    original_filename = models.CharField(max_length=255)
    file = models.FileField(upload_to=form_entry_attachment_upload_to, max_length=500)
    content_type = models.CharField(max_length=120)
    size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="form_entry_attachments_uploaded",
    )
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="form_entry_signatures_signed",
    )
    signed_at = models.DateTimeField(null=True, blank=True)
    signature_hash = models.CharField(max_length=64, blank=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="form_entry_attachments_deleted",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["field_key", "-created_at"]
        indexes = [
            models.Index(fields=["entry", "field_key", "deleted_at"]),
            models.Index(fields=["entry", "kind"]),
            models.Index(fields=["uploaded_by", "created_at"]),
        ]
        verbose_name = "Formular-Anhang"
        verbose_name_plural = "Formular-Anhaenge"

    @property
    def is_deleted(self) -> bool:
        return bool(self.deleted_at)

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    def mark_deleted(self, *, user=None) -> None:
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=["deleted_at", "deleted_by", "updated_at"])

    def clean(self) -> None:
        errors = {}
        if self.field_id and self.entry_id and self.field.form_id != self.entry.form_id:
            errors["field"] = "Der Anhang gehoert nicht zum Formular dieses Vorgangs."
        if self.kind == self.AttachmentKind.SIGNATURE:
            if not self.signed_at:
                errors["signed_at"] = "Unterschriften brauchen einen Zeitstempel."
            if not self.signature_hash:
                errors["signature_hash"] = "Unterschriften brauchen einen Hashwert."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.entry_id} {self.field_key} {self.original_filename}"
