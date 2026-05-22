from __future__ import annotations

from django import forms

from .models import Field, Form, FormSection
from .repeatable_models import RepeatableGroup, RepeatableGroupColumn


class RepeatableGroupBuilderForm(forms.ModelForm):
    class Meta:
        model = RepeatableGroup
        fields = ("section", "position", "key", "title", "description", "min_rows", "max_rows", "is_active")
        labels = {
            "section": "Abschnitt",
            "position": "Reihenfolge",
            "key": "Technischer Tabellen-Key",
            "title": "Titel",
            "description": "Beschreibung",
            "min_rows": "Mindestzeilen",
            "max_rows": "Maximalzeilen",
            "is_active": "Aktiv",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, form_definition: Form, **kwargs):
        self.form_definition = form_definition
        super().__init__(*args, **kwargs)
        self.fields["section"].queryset = FormSection.objects.filter(form=form_definition).order_by("position", "title")
        self.fields["section"].required = False
        if not self.instance.pk:
            last = RepeatableGroup.objects.filter(form=form_definition).order_by("-position").values_list("position", flat=True).first() or 0
            self.fields["position"].initial = last + 1
            self.fields["min_rows"].initial = 0
            self.fields["max_rows"].initial = 10
            self.fields["is_active"].initial = True

    def clean_section(self):
        section = self.cleaned_data.get("section")
        if section and section.form_id != self.form_definition.pk:
            raise forms.ValidationError("Dieser Abschnitt gehoert nicht zu diesem Formular.")
        return section

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.form = self.form_definition
        if commit:
            instance.save()
        return instance


class RepeatableColumnBuilderForm(forms.ModelForm):
    choices_text = forms.CharField(
        required=False,
        label="Auswahlwerte",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Nur fuer Auswahlspalten. Eine Option pro Zeile: wert|Label oder nur Label.",
    )

    class Meta:
        model = RepeatableGroupColumn
        fields = (
            "position",
            "key",
            "label",
            "column_type",
            "required",
            "help_text",
            "placeholder",
            "choices_text",
            "is_active",
        )
        labels = {
            "position": "Reihenfolge",
            "key": "Technischer Name",
            "label": "Label",
            "column_type": "Spaltentyp",
            "required": "Pflichtspalte",
            "help_text": "Hilfetext",
            "placeholder": "Platzhalter",
            "is_active": "Aktiv",
        }
        widgets = {"help_text": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, group: RepeatableGroup, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            last = group.columns.order_by("-position").values_list("position", flat=True).first() or 0
            self.fields["position"].initial = last + 1
            self.fields["is_active"].initial = True
        else:
            self.fields["choices_text"].initial = self._choices_as_text()

    def _choices_as_text(self) -> str:
        lines = []
        for choice in self.instance.choices or []:
            value = choice.get("value", "")
            label = choice.get("label", value)
            lines.append(f"{value}|{label}" if value != label else str(label))
        return "\n".join(lines)

    def clean_choices_text(self):
        raw = self.cleaned_data.get("choices_text") or ""
        choices = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                value, label = line.split("|", 1)
                value = value.strip()
                label = label.strip()
            else:
                value = label = line
            choices.append({"value": value, "label": label})
        return choices

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("column_type") == RepeatableGroupColumn.ColumnType.SELECT and not cleaned.get("choices_text"):
            self.add_error("choices_text", "Auswahlspalten brauchen mindestens einen Eintrag.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.group = self.group
        instance.choices = self.cleaned_data.get("choices_text") or []
        if instance.column_type == RepeatableGroupColumn.ColumnType.FILE:
            config = dict(instance.ui_config or {})
            config.setdefault("accept", "image/*")
            config.setdefault("capture", "environment")
            instance.ui_config = config
            rules = dict(instance.validation_rules or {})
            rules.setdefault("allowed_content_types", ["image/jpeg", "image/png", "image/webp"])
            rules.setdefault("max_size_mb", 10)
            instance.validation_rules = rules
        if commit:
            instance.save()
        return instance
