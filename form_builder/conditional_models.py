from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from .models import Field, Form, FormSection, TimeStampedModel, UUIDPrimaryKeyModel, UserStampedModel


class ConditionalRule(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    """Simple reusable rule for conditional dynamic-form behaviour.

    A rule belongs to one form version. Published forms are already protected by the
    builder workflow, so rules should be edited only on draft forms. Runtime
    validation evaluates these rules server-side; frontend JavaScript only mirrors
    them for better usability.
    """

    class Operator(models.TextChoices):
        EQUALS = "equals", "ist gleich"
        NOT_EQUALS = "not_equals", "ist nicht gleich"
        IS_EMPTY = "is_empty", "ist leer"
        IS_NOT_EMPTY = "is_not_empty", "ist nicht leer"

    class Action(models.TextChoices):
        SHOW = "show", "anzeigen"
        HIDE = "hide", "ausblenden"
        REQUIRE = "require", "verpflichtend machen"

    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="conditional_rules")
    source_field = models.ForeignKey(
        Field,
        on_delete=models.CASCADE,
        related_name="conditional_rules_as_source",
        help_text="Feld, dessen Wert die Regel ausloest.",
    )
    operator = models.CharField(max_length=24, choices=Operator.choices, default=Operator.EQUALS)
    value = models.CharField(
        max_length=255,
        blank=True,
        help_text="Vergleichswert fuer equals/not_equals. Bei Leer-Operatoren frei lassen.",
    )
    action = models.CharField(max_length=16, choices=Action.choices, default=Action.SHOW)
    target_field = models.ForeignKey(
        Field,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conditional_rules_as_target",
        help_text="Zielfeld fuer show/hide/require.",
    )
    target_section = models.ForeignKey(
        FormSection,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conditional_rules_as_target",
        help_text="Optionaler Zielabschnitt. Genau ein Ziel muss gesetzt sein.",
    )
    message = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optionale Fehlermeldung fuer require-Regeln.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["form", "source_field__position", "action", "created_at"]
        indexes = [
            models.Index(fields=["form", "is_active"]),
            models.Index(fields=["source_field", "operator"]),
            models.Index(fields=["target_field", "action"]),
            models.Index(fields=["target_section", "action"]),
        ]
        verbose_name = "Bedingte Formularregel"
        verbose_name_plural = "Bedingte Formularregeln"

    def clean(self) -> None:
        errors = {}
        if self.source_field_id and self.form_id and self.source_field.form_id != self.form_id:
            errors["source_field"] = "Das Quellfeld gehoert nicht zu diesem Formular."
        if self.target_field_id and self.form_id and self.target_field.form_id != self.form_id:
            errors["target_field"] = "Das Zielfeld gehoert nicht zu diesem Formular."
        if self.target_section_id and self.form_id and self.target_section.form_id != self.form_id:
            errors["target_section"] = "Der Zielabschnitt gehoert nicht zu diesem Formular."
        if bool(self.target_field_id) == bool(self.target_section_id):
            errors["target_field"] = "Bitte genau ein Ziel waehlen: Feld oder Abschnitt."
            errors["target_section"] = "Bitte genau ein Ziel waehlen: Feld oder Abschnitt."
        if self.target_field_id and self.source_field_id == self.target_field_id:
            errors["target_field"] = "Ein Feld darf nicht gleichzeitig Quelle und Ziel derselben Regel sein."
        if self.operator in {self.Operator.IS_EMPTY, self.Operator.IS_NOT_EMPTY} and self.value:
            errors["value"] = "Bei Leer-Operatoren darf kein Vergleichswert gesetzt werden."
        if self.operator in {self.Operator.EQUALS, self.Operator.NOT_EQUALS} and self.value == "":
            errors["value"] = "Bitte einen Vergleichswert angeben."
        if errors:
            raise ValidationError(errors)

    @property
    def target_kind(self) -> str:
        return "section" if self.target_section_id else "field"

    @property
    def target_key(self) -> str:
        if self.target_section_id:
            return str(self.target_section_id)
        return self.target_field.key if self.target_field_id else ""

    def as_runtime_dict(self) -> dict:
        return {
            "id": str(self.pk),
            "source": self.source_field.key,
            "operator": self.operator,
            "value": self.value,
            "action": self.action,
            "target_kind": self.target_kind,
            "target": self.target_key,
            "message": self.message,
        }

    def __str__(self) -> str:
        return f"{self.form.key}: {self.source_field.key} {self.operator} -> {self.action} {self.target_key}"
