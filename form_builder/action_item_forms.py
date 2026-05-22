from __future__ import annotations

from django import forms

from .action_item_models import ActionItem, ActionItemRule
from .action_item_services import user_queryset_for_assignment
from .models import Field


class ActionItemStatusForm(forms.ModelForm):
    note = forms.CharField(label="Notiz", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    class Meta:
        model = ActionItem
        fields = ["status", "assigned_to", "due_at", "priority", "note"]
        widgets = {"due_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = user_queryset_for_assignment()


class ActionItemRuleForm(forms.ModelForm):
    source_mode = forms.ChoiceField(
        label="Quelle",
        choices=[("field", "Einzelfeld"), ("table", "Tabellenspalte")],
        initial="field",
    )

    class Meta:
        model = ActionItemRule
        fields = [
            "name",
            "source_mode",
            "source_field",
            "source_field_key",
            "source_group_key",
            "source_column_key",
            "operator",
            "value",
            "title_template",
            "description_template",
            "assigned_to",
            "assigned_to_field_key",
            "due_at_field_key",
            "priority",
            "is_active",
        ]
        widgets = {"description_template": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, form_definition=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.form_definition = form_definition or getattr(self.instance, "form", None)
        self.fields["assigned_to"].queryset = user_queryset_for_assignment()
        if self.form_definition:
            self.fields["source_field"].queryset = Field.objects.filter(
                form=self.form_definition, is_active=True
            ).order_by("position", "key")
        if self.instance and self.instance.pk and self.instance.source_group_key:
            self.fields["source_mode"].initial = "table"

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("source_mode")
        if mode == "field":
            cleaned["source_group_key"] = ""
            cleaned["source_column_key"] = ""
            if not cleaned.get("source_field") and not cleaned.get("source_field_key"):
                self.add_error("source_field", "Bitte ein Quellfeld waehlen.")
        else:
            cleaned["source_field"] = None
            cleaned["source_field_key"] = ""
            if not cleaned.get("source_group_key") or not cleaned.get("source_column_key"):
                self.add_error("source_group_key", "Bitte Gruppe und Spalte angeben.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.form_definition and not instance.form_id:
            instance.form = self.form_definition
        mode = self.cleaned_data.get("source_mode")
        if mode == "field":
            instance.source_group_key = ""
            instance.source_column_key = ""
            if instance.source_field_id:
                instance.source_field_key = ""
        else:
            instance.source_field = None
            instance.source_field_key = ""
        if commit:
            instance.save()
        return instance
