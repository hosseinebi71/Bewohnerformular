from __future__ import annotations

from django import forms

from .form_template_models import FormTemplate


class FormTemplateCreateForm(forms.ModelForm):
    class Meta:
        model = FormTemplate
        fields = (
            "key",
            "version",
            "title",
            "category",
            "description",
            "language",
            "tags",
            "status",
            "definition",
        )
        labels = {
            "key": "Vorlagen-Key",
            "version": "Version",
            "title": "Titel",
            "category": "Kategorie",
            "description": "Beschreibung",
            "language": "Sprache",
            "tags": "Tags",
            "status": "Status",
            "definition": "Definition (JSON)",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "tags": forms.Textarea(attrs={"rows": 2}),
            "definition": forms.Textarea(attrs={"rows": 16, "spellcheck": "false"}),
        }


class FormTemplateCopyForm(forms.Form):
    form_key = forms.SlugField(label="Neuer Formular-Key", max_length=80)
    title = forms.CharField(label="Titel", max_length=255)
    org_unit = forms.CharField(label="Organisationseinheit", max_length=80, required=False)

    def __init__(self, *args, template: FormTemplate, **kwargs):
        super().__init__(*args, **kwargs)
        form_meta = (template.definition or {}).get("form", {})
        self.fields["form_key"].initial = form_meta.get("key") or template.key
        self.fields["title"].initial = form_meta.get("title") or template.title
        self.fields["org_unit"].initial = form_meta.get("org_unit", "")
