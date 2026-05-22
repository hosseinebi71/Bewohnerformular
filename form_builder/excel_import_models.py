from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import get_valid_filename

from .models import TimeStampedModel, UUIDPrimaryKeyModel


SUPPORTED_EXCEL_EXTENSIONS = {".xlsx"}


def excel_import_upload_to(instance, filename: str) -> str:
    safe_name = get_valid_filename(os.path.basename(filename or "workbook.xlsx"))[:180]
    job_id = instance.pk or uuid.uuid4()
    return f"private/excel_imports/{job_id}/{safe_name}"


class ImportJob(UUIDPrimaryKeyModel, TimeStampedModel):
    class ImportStatus(models.TextChoices):
        UPLOADED = "uploaded", "Hochgeladen"
        ANALYZED = "analyzed", "Analysiert"
        MAPPED = "mapped", "Mapping gespeichert"
        GENERATED = "generated", "Entwuerfe erzeugt"
        FAILED = "failed", "Fehlgeschlagen"

    uploaded_file = models.FileField(upload_to=excel_import_upload_to, max_length=500)
    original_filename = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="excel_import_jobs",
    )
    status = models.CharField(
        max_length=24,
        choices=ImportStatus.choices,
        default=ImportStatus.UPLOADED,
        db_index=True,
    )
    error_message = models.TextField(blank=True)
    analysis_result = models.JSONField(default=dict, blank=True)
    mapping = models.JSONField(default=dict, blank=True)
    generated_form_ids = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["uploaded_by", "created_at"]),
        ]
        verbose_name = "Excel-Import"
        verbose_name_plural = "Excel-Importe"

    def clean(self) -> None:
        errors = {}
        filename = self.original_filename or getattr(self.uploaded_file, "name", "")
        ext = os.path.splitext(filename.lower())[1]
        if ext and ext not in SUPPORTED_EXCEL_EXTENSIONS:
            errors["uploaded_file"] = "Bitte eine echte .xlsx-Datei hochladen. Makro-Dateien werden nicht akzeptiert."
        if not isinstance(self.analysis_result, dict):
            errors["analysis_result"] = "Analyseergebnis muss als JSON-Objekt gespeichert werden."
        if not isinstance(self.mapping, dict):
            errors["mapping"] = "Mapping muss als JSON-Objekt gespeichert werden."
        if not isinstance(self.generated_form_ids, list):
            errors["generated_form_ids"] = "Generierte Formulare muessen als Liste gespeichert werden."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.original_filename} - {self.get_status_display()}"


class ImportedSheet(UUIDPrimaryKeyModel, TimeStampedModel):
    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="sheets")
    sheet_index = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    used_range = models.CharField(max_length=64, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    column_count = models.PositiveIntegerField(default=0)
    analysis = models.JSONField(default=dict, blank=True)
    selected = models.BooleanField(default=True)

    class Meta:
        ordering = ["job", "sheet_index"]
        constraints = [
            models.UniqueConstraint(fields=["job", "sheet_index"], name="uniq_imported_sheet_index"),
            models.UniqueConstraint(fields=["job", "name"], name="uniq_imported_sheet_name"),
        ]
        indexes = [models.Index(fields=["job", "selected"])]
        verbose_name = "Importiertes Excel-Blatt"
        verbose_name_plural = "Importierte Excel-Blaetter"

    def clean(self) -> None:
        if not isinstance(self.analysis, dict):
            raise ValidationError({"analysis": "Blattanalyse muss als JSON-Objekt gespeichert werden."})

    def __str__(self) -> str:
        return f"{self.job_id} - {self.name}"


class FieldMapping(UUIDPrimaryKeyModel, TimeStampedModel):
    class TargetKind(models.TextChoices):
        FIELD = "field", "Feld"
        SECTION = "section", "Abschnitt"
        TABLE = "table", "Tabelle"
        COLUMN = "column", "Tabellenspalte"

    class FieldType(models.TextChoices):
        TEXT = "text", "Text"
        TEXTAREA = "textarea", "Mehrzeilig"
        CHECKBOX = "checkbox", "Checkbox"
        DATE = "date", "Datum"
        NUMBER = "number", "Zahl"
        SELECT = "select", "Auswahl"
        TABLE = "table", "Tabelle"
        FILE = "file", "Datei/Foto"

    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="field_mappings")
    sheet = models.ForeignKey(
        ImportedSheet,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="field_mappings",
    )
    source_ref = models.CharField(max_length=120, blank=True)
    target_kind = models.CharField(max_length=24, choices=TargetKind.choices, default=TargetKind.FIELD)
    target_key = models.SlugField(max_length=80)
    label = models.CharField(max_length=255)
    field_type = models.CharField(max_length=24, choices=FieldType.choices, default=FieldType.TEXT)
    required = models.BooleanField(default=False)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["job", "sheet__sheet_index", "target_kind", "created_at"]
        indexes = [
            models.Index(fields=["job", "target_kind"]),
            models.Index(fields=["sheet", "target_kind"]),
        ]
        verbose_name = "Excel-Feldmapping"
        verbose_name_plural = "Excel-Feldmappings"

    def clean(self) -> None:
        if self.sheet_id and self.job_id and self.sheet.job_id != self.job_id:
            raise ValidationError({"sheet": "Das Blatt gehoert nicht zu diesem Importjob."})
        if not isinstance(self.config, dict):
            raise ValidationError({"config": "Mapping-Konfiguration muss als JSON-Objekt gespeichert werden."})

    def __str__(self) -> str:
        return f"{self.label} -> {self.target_key}"
