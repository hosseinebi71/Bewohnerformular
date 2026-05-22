from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .models import Field, Form, FormEntry, TimeStampedModel, UUIDPrimaryKeyModel, UserStampedModel


class ActionItem(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    """Trackable measure/task created manually or from a form submission."""

    class Priority(models.TextChoices):
        LOW = "low", "Niedrig"
        NORMAL = "normal", "Normal"
        HIGH = "high", "Hoch"
        CRITICAL = "critical", "Kritisch"

    class Status(models.TextChoices):
        OPEN = "open", "Offen"
        IN_PROGRESS = "in_progress", "In Bearbeitung"
        DONE = "done", "Erledigt"
        VERIFIED = "verified", "Verifiziert"
        CANCELLED = "cancelled", "Abgebrochen"

    source_entry = models.ForeignKey(
        FormEntry,
        on_delete=models.CASCADE,
        related_name="action_items",
    )
    source_field = models.ForeignKey(
        Field,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_items",
    )
    source_field_key = models.SlugField(max_length=120, blank=True, db_index=True)
    source_group_key = models.SlugField(max_length=120, blank=True, db_index=True)
    source_row_key = models.CharField(max_length=120, blank=True, db_index=True)
    source_rule_key = models.CharField(max_length=160, blank=True, db_index=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_action_items",
    )
    assigned_to_label = models.CharField(
        max_length=255,
        blank=True,
        help_text="Freitext-Verantwortlicher aus importierten Tabellen, falls kein Benutzer zugeordnet ist.",
    )
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_action_items",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["status", "due_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_entry", "source_rule_key", "source_row_key", "source_field_key"],
                name="uniq_action_item_source_dedupe",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "due_at"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["source_entry", "status"]),
            models.Index(fields=["source_group_key", "source_row_key"]),
        ]
        verbose_name = "Massnahme"
        verbose_name_plural = "Massnahmen"

    @property
    def is_closed(self) -> bool:
        return self.status in {self.Status.DONE, self.Status.VERIFIED, self.Status.CANCELLED}

    def clean(self) -> None:
        errors = {}
        if self.source_field_id and self.source_entry_id:
            if self.source_field.form_id != self.source_entry.form_id:
                errors["source_field"] = "Das Quellfeld gehoert nicht zum Formular des Vorgangs."
        if self.status == self.Status.DONE and not self.completed_at:
            self.completed_at = timezone.now()
        if self.status == self.Status.VERIFIED and not self.verified_at:
            self.verified_at = timezone.now()
        if self.status == self.Status.VERIFIED and not self.verified_by_id:
            errors["verified_by"] = "Verifizierte Massnahmen brauchen eine pruefende Person."
        if self.status == self.Status.CANCELLED and not self.cancelled_at:
            self.cancelled_at = timezone.now()
        if not isinstance(self.metadata, dict):
            errors["metadata"] = "Metadaten muessen als Objekt gespeichert werden."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.title} - {self.get_status_display()}"


class ActionItemRule(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    """Configurable rule that creates ActionItems from submitted form values."""

    class Operator(models.TextChoices):
        EQUALS = "equals", "ist gleich"
        NOT_EQUALS = "not_equals", "ist nicht gleich"
        CONTAINS = "contains", "enthaelt"
        IS_EMPTY = "is_empty", "ist leer"
        IS_NOT_EMPTY = "is_not_empty", "ist nicht leer"
        BOOLEAN_TRUE = "boolean_true", "ist ja/aktiv"
        BOOLEAN_FALSE = "boolean_false", "ist nein/inaktiv"

    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="action_item_rules")
    name = models.CharField(max_length=255)
    source_field = models.ForeignKey(
        Field,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="action_item_rules",
    )
    source_field_key = models.SlugField(max_length=120, blank=True)
    source_group_key = models.SlugField(max_length=120, blank=True)
    source_column_key = models.SlugField(max_length=120, blank=True)
    operator = models.CharField(max_length=24, choices=Operator.choices, default=Operator.EQUALS)
    value = models.CharField(max_length=255, blank=True)
    title_template = models.CharField(max_length=255, default="Massnahme aus {form}")
    description_template = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_item_rules_assigned",
    )
    assigned_to_field_key = models.SlugField(max_length=120, blank=True)
    due_at_field_key = models.SlugField(max_length=120, blank=True)
    priority = models.CharField(
        max_length=16,
        choices=ActionItem.Priority.choices,
        default=ActionItem.Priority.NORMAL,
    )
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["form", "name"]
        indexes = [
            models.Index(fields=["form", "is_active"]),
            models.Index(fields=["source_group_key", "source_column_key"]),
        ]
        verbose_name = "Massnahmen-Regel"
        verbose_name_plural = "Massnahmen-Regeln"

    def clean(self) -> None:
        errors = {}
        if self.source_field_id and self.source_field.form_id != self.form_id:
            errors["source_field"] = "Das Quellfeld gehoert nicht zu diesem Formular."
        has_simple_source = bool(self.source_field_id or self.source_field_key)
        has_table_source = bool(self.source_group_key and self.source_column_key)
        if has_simple_source == has_table_source:
            errors["source_field"] = "Bitte entweder ein Formularfeld oder eine Tabellenspalte als Quelle setzen."
        if self.operator in {self.Operator.EQUALS, self.Operator.NOT_EQUALS, self.Operator.CONTAINS}:
            if self.value == "":
                errors["value"] = "Bitte einen Vergleichswert angeben."
        elif self.value:
            errors["value"] = "Bei diesem Operator darf kein Vergleichswert gesetzt werden."
        if not isinstance(self.config, dict):
            errors["config"] = "Konfiguration muss als Objekt gespeichert werden."
        if errors:
            raise ValidationError(errors)

    @property
    def source_key(self) -> str:
        return self.source_field.key if self.source_field_id else self.source_field_key

    def __str__(self) -> str:
        return f"{self.form.key}: {self.name}"


class ActionItemReminderLog(UUIDPrimaryKeyModel, TimeStampedModel):
    """Deduplication log for task/review reminder generation."""

    class ReminderKind(models.TextChoices):
        DUE_SOON = "due_soon", "Bald faellig"
        OVERDUE = "overdue", "Ueberfaellig"
        ESCALATION = "escalation", "Eskalation"
        REVIEW_OVERDUE = "review_overdue", "Review ueberfaellig"

    action_item = models.ForeignKey(
        ActionItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reminder_logs",
    )
    form_entry = models.ForeignKey(
        FormEntry,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reminder_logs",
    )
    kind = models.CharField(max_length=32, choices=ReminderKind.choices)
    dedupe_key = models.CharField(max_length=255, unique=True)
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-sent_at"]
        indexes = [
            models.Index(fields=["kind", "sent_at"]),
            models.Index(fields=["action_item", "kind"]),
            models.Index(fields=["form_entry", "kind"]),
        ]
        verbose_name = "Massnahmen-Erinnerung"
        verbose_name_plural = "Massnahmen-Erinnerungen"

    def __str__(self) -> str:
        return f"{self.kind} {self.dedupe_key}"
