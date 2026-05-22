from __future__ import annotations

import hashlib
import os
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import get_valid_filename

from .models import Field, Form, TimeStampedModel, UserStampedModel, UUIDPrimaryKeyModel

MAX_TEMPLATE_SIZE_BYTES = 25 * 1024 * 1024


def pdf_template_upload_to(instance, filename: str) -> str:
    safe_name = get_valid_filename(os.path.basename(filename or "template.pdf"))[:180]
    form_key = get_valid_filename(getattr(instance.form, "key", "form") or "form")[:80]
    return f"private/pdf_templates/{form_key}/{uuid.uuid4().hex}_{safe_name}"


def calculate_file_sha256(uploaded_file) -> str:
    digest = hashlib.sha256()
    position = None
    if hasattr(uploaded_file, "tell") and hasattr(uploaded_file, "seek"):
        try:
            position = uploaded_file.tell()
            uploaded_file.seek(0)
        except Exception:
            position = None
    chunks = uploaded_file.chunks() if hasattr(uploaded_file, "chunks") else [uploaded_file.read()]
    for chunk in chunks:
        digest.update(chunk)
    if position is not None:
        uploaded_file.seek(position)
    return digest.hexdigest()


def validate_pdf_upload(uploaded_file) -> None:
    filename = getattr(uploaded_file, "name", "template.pdf") or "template.pdf"
    content_type = (getattr(uploaded_file, "content_type", "") or "").split(";", 1)[0].strip()
    size = int(getattr(uploaded_file, "size", 0) or 0)
    if not filename.lower().endswith(".pdf"):
        raise ValidationError("Nur PDF-Dateien koennen als Vorlage hochgeladen werden.")
    if content_type and content_type not in {"application/pdf", "application/octet-stream"}:
        raise ValidationError(f"Dateityp {content_type} ist keine erlaubte PDF-Vorlage.")
    if size <= 0:
        raise ValidationError("Die PDF-Datei ist leer.")
    if size > MAX_TEMPLATE_SIZE_BYTES:
        raise ValidationError("Die PDF-Vorlage ist zu gross. Maximal erlaubt sind 25 MB.")


class PDFTemplate(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class TemplateStatus(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        ACTIVE = "active", "Aktiv"
        RETIRED = "retired", "Ausgemustert"

    form = models.ForeignKey(Form, on_delete=models.PROTECT, related_name="pdf_templates")
    name = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    file = models.FileField(upload_to=pdf_template_upload_to, max_length=500)
    content_type = models.CharField(max_length=100, default="application/pdf")
    file_size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    page_count = models.PositiveIntegerField(default=0)
    page_metadata = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16,
        choices=TemplateStatus.choices,
        default=TemplateStatus.DRAFT,
        db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["form", "-created_at"]
        indexes = [
            models.Index(fields=["form", "status", "is_active"]),
            models.Index(fields=["sha256"]),
        ]
        verbose_name = "PDF-Vorlage"
        verbose_name_plural = "PDF-Vorlagen"

    def clean(self) -> None:
        errors = {}
        if self.page_count < 0:
            errors["page_count"] = "Seitenanzahl darf nicht negativ sein."
        if not isinstance(self.page_metadata, list):
            errors["page_metadata"] = "Seitenmetadaten muessen als Liste gespeichert werden."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.form.key} - {self.name}"


class PDFTemplatePlacement(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class PlacementKind(models.TextChoices):
        TEXT = "text", "Text"
        CHECKBOX = "checkbox", "Checkbox"
        DATE = "date", "Datum"
        SIGNATURE = "signature", "Unterschrift"

    template = models.ForeignKey(PDFTemplate, on_delete=models.CASCADE, related_name="placements")
    field = models.ForeignKey(
        Field, on_delete=models.CASCADE, related_name="pdf_template_placements"
    )
    page_number = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    x = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    y = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    width = models.FloatField(validators=[MinValueValidator(0.001), MaxValueValidator(1.0)])
    height = models.FloatField(validators=[MinValueValidator(0.001), MaxValueValidator(1.0)])
    kind = models.CharField(
        max_length=24, choices=PlacementKind.choices, default=PlacementKind.TEXT
    )
    font_size = models.PositiveIntegerField(
        default=10, validators=[MinValueValidator(6), MaxValueValidator(28)]
    )
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["template", "page_number", "field__position", "field__key"]
        indexes = [
            models.Index(fields=["template", "page_number", "is_active"]),
            models.Index(fields=["field", "is_active"]),
        ]
        verbose_name = "PDF-Feldplatzierung"
        verbose_name_plural = "PDF-Feldplatzierungen"

    def clean(self) -> None:
        errors = {}
        if self.template_id and self.field_id and self.field.form_id != self.template.form_id:
            errors["field"] = "Das Feld gehoert nicht zum Formular dieser PDF-Vorlage."
        if self.template_id and self.page_number > max(int(self.template.page_count or 0), 1):
            errors["page_number"] = "Diese Seite existiert in der PDF-Vorlage nicht."
        if self.x + self.width > 1.000001:
            errors["width"] = "X plus Breite muss innerhalb der Seite bleiben."
        if self.y + self.height > 1.000001:
            errors["height"] = "Y plus Hoehe muss innerhalb der Seite bleiben."
        if not isinstance(self.config, dict):
            errors["config"] = "Konfiguration muss als Objekt gespeichert werden."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.template_id} p{self.page_number}: {self.field.key}"
