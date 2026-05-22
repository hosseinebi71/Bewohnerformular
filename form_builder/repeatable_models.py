from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

from .models import Field, Form, FormSection, TimeStampedModel, UserStampedModel, UUIDPrimaryKeyModel


class RepeatableGroup(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    """A reusable repeatable table/group definition for dynamic forms.

    Data is stored in FormEntry.data under this group's key as a list of row
    dictionaries. Each row contains values keyed by RepeatableGroupColumn.key.
    """

    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="repeatable_groups")
    section = models.ForeignKey(
        FormSection,
        on_delete=models.SET_NULL,
        related_name="repeatable_groups",
        null=True,
        blank=True,
    )
    key = models.SlugField(max_length=80)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    min_rows = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    max_rows = models.PositiveIntegerField(default=25, validators=[MinValueValidator(1), MaxValueValidator(200)])
    is_active = models.BooleanField(default=True)
    ui_config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["form", "position", "title"]
        constraints = [
            models.UniqueConstraint(fields=["form", "key"], name="uniq_repeatable_group_key_per_form"),
            models.CheckConstraint(condition=models.Q(max_rows__gte=models.F("min_rows")), name="repeatable_group_max_gte_min"),
        ]
        indexes = [
            models.Index(fields=["form", "is_active"]),
            models.Index(fields=["section", "is_active"]),
        ]
        verbose_name = "Wiederholbare Tabelle"
        verbose_name_plural = "Wiederholbare Tabellen"

    def clean(self) -> None:
        errors = {}
        if self.section_id and self.form_id and self.section.form_id != self.form_id:
            errors["section"] = "Der Abschnitt gehoert nicht zu diesem Formular."
        if self.max_rows < self.min_rows:
            errors["max_rows"] = "Maximale Zeilenanzahl muss groesser/gleich Minimum sein."
        if not isinstance(self.ui_config, dict):
            errors["ui_config"] = "UI-Konfiguration muss als Objekt gespeichert werden."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = slugify(self.title)[:80]
        self.full_clean()
        super().save(*args, **kwargs)

    def as_builder_dict(self) -> dict:
        columns = [
            column.as_builder_dict()
            for column in self.columns.filter(is_active=True).order_by("position", "key")
        ]
        return {
            "id": str(self.id),
            "key": self.key,
            "section_id": str(self.section_id) if self.section_id else None,
            "title": self.title,
            "description": self.description,
            "position": self.position,
            "min_rows": self.min_rows,
            "max_rows": self.max_rows,
            "columns": columns,
            "column_keys": [column["key"] for column in columns],
            "ui_config": self.ui_config,
            "is_active": self.is_active,
        }

    def __str__(self) -> str:
        return f"{self.form.key}.{self.key}"


class RepeatableGroupColumn(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class ColumnType(models.TextChoices):
        TEXT = "text", "Text"
        TEXTAREA = "textarea", "Mehrzeilig"
        INTEGER = "integer", "Ganzzahl"
        DECIMAL = "decimal", "Dezimalzahl"
        DATE = "date", "Datum"
        BOOLEAN = "boolean", "Checkbox"
        SELECT = "select", "Auswahl"
        FILE = "file", "Datei/Foto"

    group = models.ForeignKey(RepeatableGroup, on_delete=models.CASCADE, related_name="columns")
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=255)
    help_text = models.TextField(blank=True)
    column_type = models.CharField(max_length=24, choices=ColumnType.choices, default=ColumnType.TEXT)
    position = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    required = models.BooleanField(default=False)
    placeholder = models.CharField(max_length=255, blank=True)
    choices = models.JSONField(default=list, blank=True)
    validation_rules = models.JSONField(default=dict, blank=True)
    ui_config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["group", "position", "key"]
        constraints = [
            models.UniqueConstraint(fields=["group", "key"], name="uniq_repeatable_column_key_per_group"),
            models.UniqueConstraint(fields=["group", "position"], name="uniq_repeatable_column_position_per_group"),
        ]
        indexes = [
            models.Index(fields=["group", "is_active"]),
            models.Index(fields=["column_type"]),
        ]
        verbose_name = "Tabellenspalte"
        verbose_name_plural = "Tabellenspalten"

    def clean(self) -> None:
        errors = {}
        if self.column_type == self.ColumnType.SELECT:
            if not isinstance(self.choices, list) or not self.choices:
                errors["choices"] = "Auswahlspalten brauchen mindestens einen Eintrag."
            elif any(not isinstance(choice, dict) or "value" not in choice or "label" not in choice for choice in self.choices):
                errors["choices"] = "Jede Auswahloption muss value und label enthalten."
        elif self.choices:
            errors["choices"] = "Auswahlwerte sind nur fuer Auswahlspalten erlaubt."
        if not isinstance(self.validation_rules, dict):
            errors["validation_rules"] = "Validierungsregeln muessen als Objekt gespeichert werden."
        if not isinstance(self.ui_config, dict):
            errors["ui_config"] = "UI-Konfiguration muss als Objekt gespeichert werden."
        if errors:
            raise ValidationError(errors)

    @property
    def field_type(self) -> str:
        # Used by the shared validation/upload helpers that expect Field.FieldType-like keys.
        return self.column_type

    def as_builder_dict(self) -> dict:
        return {
            "id": str(self.id),
            "key": self.key,
            "label": self.label,
            "help_text": self.help_text,
            "field_type": self.column_type,
            "position": self.position,
            "required": self.required,
            "placeholder": self.placeholder,
            "choices": self.choices,
            "validation_rules": self.validation_rules,
            "ui_config": self.ui_config,
            "is_active": self.is_active,
        }

    def __str__(self) -> str:
        return f"{self.group.key}.{self.key}"
