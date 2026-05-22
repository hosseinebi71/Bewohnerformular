from __future__ import annotations

from django import forms

from .conditional_models import ConditionalRule
from .models import Field, FormSection


class ConditionalRuleForm(forms.ModelForm):
    class Meta:
        model = ConditionalRule
        fields = (
            "source_field",
            "operator",
            "value",
            "action",
            "target_field",
            "target_section",
            "message",
            "is_active",
        )
        labels = {
            "source_field": "Quellfeld",
            "operator": "Operator",
            "value": "Wert",
            "action": "Aktion",
            "target_field": "Zielfeld",
            "target_section": "Zielabschnitt",
            "message": "Fehlermeldung bei Pflichtregel",
            "is_active": "Aktiv",
        }
        help_texts = {
            "value": "Bei equals/not_equals Wert wie im Formular speichern, z. B. yes oder true.",
            "target_section": "Nur auswaehlen, wenn kein Zielfeld gesetzt ist.",
        }

    def __init__(self, *args, form_definition, **kwargs):
        self.form_definition = form_definition
        super().__init__(*args, **kwargs)
        fields = Field.objects.filter(form=form_definition, is_active=True).order_by(
            "position", "key"
        )
        sections = FormSection.objects.filter(form=form_definition, is_active=True).order_by(
            "position", "title"
        )
        self.fields["source_field"].queryset = fields
        self.fields["target_field"].queryset = fields
        self.fields["target_section"].queryset = sections
        self.fields["target_field"].required = False
        self.fields["target_section"].required = False
        self.fields["message"].required = False
        self.fields["is_active"].required = False

    def clean(self):
        cleaned = super().clean()
        target_field = cleaned.get("target_field")
        target_section = cleaned.get("target_section")
        source_field = cleaned.get("source_field")
        if bool(target_field) == bool(target_section):
            raise forms.ValidationError("Bitte genau ein Ziel waehlen: Feld oder Abschnitt.")
        if source_field and target_field and source_field.pk == target_field.pk:
            self.add_error("target_field", "Quelle und Ziel duerfen nicht dasselbe Feld sein.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.form = self.form_definition
        if commit:
            instance.save()
        return instance
