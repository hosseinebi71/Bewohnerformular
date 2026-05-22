from __future__ import annotations

from django import forms

from .models import Field, Form
from .pdf_template_models import PDFTemplate, PDFTemplatePlacement, validate_pdf_upload


class PDFTemplateUploadForm(forms.Form):
    form = forms.ModelChoiceField(
        queryset=Form.objects.order_by("title", "key"),
        label="Formular",
        help_text="Das digitale Formular, zu dem diese PDF-Vorlage gehoert.",
    )
    name = forms.CharField(max_length=255, label="Name", required=False)
    file = forms.FileField(label="PDF-Datei")

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        validate_pdf_upload(uploaded_file)
        return uploaded_file


class PDFTemplatePlacementForm(forms.ModelForm):
    class Meta:
        model = PDFTemplatePlacement
        fields = (
            "field",
            "page_number",
            "x",
            "y",
            "width",
            "height",
            "kind",
            "font_size",
            "is_active",
            "config",
        )
        widgets = {
            "x": forms.NumberInput(attrs={"step": "0.001", "min": "0", "max": "1"}),
            "y": forms.NumberInput(attrs={"step": "0.001", "min": "0", "max": "1"}),
            "width": forms.NumberInput(attrs={"step": "0.001", "min": "0.001", "max": "1"}),
            "height": forms.NumberInput(attrs={"step": "0.001", "min": "0.001", "max": "1"}),
            "config": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, template: PDFTemplate, **kwargs):
        self.template = template
        super().__init__(*args, **kwargs)
        self.fields["field"].queryset = Field.objects.filter(
            form=template.form,
            is_active=True,
        ).order_by("position", "key")
        self.fields["page_number"].help_text = f"1 bis {max(template.page_count, 1)}"

    def clean(self):
        cleaned_data = super().clean()
        self.instance.template = self.template
        return cleaned_data
