from __future__ import annotations

from django import forms

from .docx_template_models import DOCXTemplate, validate_docx_template_file
from .models import Form


class DOCXTemplateUploadForm(forms.Form):
    form = forms.ModelChoiceField(
        queryset=Form.objects.order_by("title", "key"),
        label="Formular",
        help_text="Die DOCX-Vorlage wird mit diesem digitalen Formular verknuepft.",
    )
    title = forms.CharField(max_length=255, label="Titel")
    description = forms.CharField(
        label="Beschreibung",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    template_file = forms.FileField(label="DOCX-Datei")
    make_default = forms.BooleanField(
        required=False,
        initial=True,
        label="Als aktive Standardvorlage verwenden",
    )

    def clean_template_file(self):
        uploaded_file = self.cleaned_data["template_file"]
        validate_docx_template_file(uploaded_file)
        return uploaded_file


class DOCXTemplateStatusForm(forms.ModelForm):
    class Meta:
        model = DOCXTemplate
        fields = ("title", "description", "status", "is_default")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
