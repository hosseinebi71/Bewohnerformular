from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import get_valid_filename

from .models import Form, TimeStampedModel, UserStampedModel, UUIDPrimaryKeyModel

DOCX_MAX_TEMPLATE_SIZE = 10 * 1024 * 1024
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
REJECTED_DOCX_SUFFIXES = {".doc", ".docm", ".dotm"}


def docx_template_upload_to(instance, filename: str) -> str:
    safe_name = get_valid_filename(os.path.basename(filename or "template.docx"))[:180]
    form_key = get_valid_filename(instance.form.key if instance.form_id else "unbound")[:80]
    return f"private/docx_templates/{form_key}/{uuid.uuid4().hex}_{safe_name}"


def validate_docx_template_file(uploaded_file) -> None:
    name = getattr(uploaded_file, "name", "") or ""
    suffix = os.path.splitext(name.lower())[1]
    if suffix != ".docx" or suffix in REJECTED_DOCX_SUFFIXES:
        raise ValidationError(
            "Bitte eine sichere .docx-Datei hochladen. .doc, .docm und Makrodateien sind nicht erlaubt."
        )
    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size > DOCX_MAX_TEMPLATE_SIZE:
        raise ValidationError("Die DOCX-Vorlage ist zu gross. Maximal erlaubt sind 10 MB.")
    content_type = (getattr(uploaded_file, "content_type", "") or "").split(";", 1)[0].strip()
    if content_type and content_type not in {DOCX_CONTENT_TYPE, "application/octet-stream"}:
        raise ValidationError(f"Dateityp {content_type} ist keine gueltige DOCX-Vorlage.")


class DOCXTemplate(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class TemplateStatus(models.TextChoices):
        ACTIVE = "active", "Aktiv"
        DRAFT = "draft", "Entwurf"
        RETIRED = "retired", "Stillgelegt"

    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="docx_templates")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    template_file = models.FileField(upload_to=docx_template_upload_to, max_length=500)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, default=DOCX_CONTENT_TYPE)
    file_size = models.PositiveBigIntegerField(default=0)
    placeholder_keys = models.JSONField(default=list, blank=True)
    analysis = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=TemplateStatus.choices,
        default=TemplateStatus.DRAFT,
        db_index=True,
    )
    is_default = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="docx_templates_uploaded",
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["form", "-created_at"]
        indexes = [
            models.Index(fields=["form", "status", "is_default"]),
            models.Index(fields=["uploaded_by", "created_at"]),
        ]
        verbose_name = "DOCX-Vorlage"
        verbose_name_plural = "DOCX-Vorlagen"

    def clean(self) -> None:
        errors = {}
        if not isinstance(self.placeholder_keys, list):
            errors["placeholder_keys"] = "Platzhalter muessen als Liste gespeichert werden."
        if not isinstance(self.analysis, dict):
            errors["analysis"] = "Analyse muss als Objekt gespeichert werden."
        if self.template_file:
            validate_docx_template_file(self.template_file)
        if errors:
            raise ValidationError(errors)

    def activate(self, *, user=None) -> None:
        DOCXTemplate.objects.filter(form=self.form, is_default=True).exclude(pk=self.pk).update(
            is_default=False,
            status=self.TemplateStatus.RETIRED,
        )
        self.status = self.TemplateStatus.ACTIVE
        self.is_default = True
        self.activated_at = timezone.now()
        self.updated_by = user
        self.save(
            update_fields=["status", "is_default", "activated_at", "updated_by", "updated_at"]
        )

    def __str__(self) -> str:
        return f"{self.form.key} - {self.title}"
