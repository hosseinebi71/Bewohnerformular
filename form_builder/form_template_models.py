from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from .models import TimeStampedModel, UserStampedModel, UUIDPrimaryKeyModel


class FormTemplate(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    """Reusable, versioned library template for creating editable forms."""

    class TemplateStatus(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        ACTIVE = "active", "Aktiv"
        RETIRED = "retired", "Ausgemustert"

    key = models.SlugField(max_length=120)
    version = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=120, blank=True, db_index=True)
    description = models.TextField(blank=True)
    language = models.CharField(max_length=16, default="de")
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16,
        choices=TemplateStatus.choices,
        default=TemplateStatus.ACTIVE,
        db_index=True,
    )
    definition = models.JSONField(
        default=dict,
        help_text=(
            "Portable template payload with form metadata, sections, fields, "
            "repeatable groups, conditional rules and action-item rules."
        ),
    )

    class Meta:
        ordering = ["category", "title", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["key", "version"], name="uniq_form_template_key_version"),
        ]
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["key", "status"]),
        ]
        verbose_name = "Formularvorlage"
        verbose_name_plural = "Formularvorlagen"

    def clean(self) -> None:
        errors = {}
        if not isinstance(self.tags, list):
            errors["tags"] = "Tags muessen als Liste gespeichert werden."
        if not isinstance(self.definition, dict):
            errors["definition"] = "Definition muss als Objekt gespeichert werden."
        if isinstance(self.definition, dict):
            fields = self.definition.get("fields", [])
            sections = self.definition.get("sections", [])
            if not fields and not sections:
                errors["definition"] = "Eine Vorlage braucht mindestens ein Feld oder einen Abschnitt."
        if errors:
            raise ValidationError(errors)

    @property
    def is_active(self) -> bool:
        return self.status == self.TemplateStatus.ACTIVE

    def __str__(self) -> str:
        return f"{self.title} v{self.version}"
