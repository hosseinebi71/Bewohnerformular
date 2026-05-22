from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from .excel_import_services import mapping_to_pretty_json, parse_mapping_json, validate_excel_upload


class ExcelImportUploadForm(forms.Form):
    uploaded_file = forms.FileField(
        label="Excel-Datei (.xlsx)",
        help_text="Nur .xlsx ohne Makros. Makro-Dateien (.xlsm) werden abgelehnt.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
    )

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data["uploaded_file"]
        validate_excel_upload(uploaded_file)
        return uploaded_file


class ExcelMappingForm(forms.Form):
    mode = forms.ChoiceField(
        label="Importmodus",
        choices=(
            ("one_form_per_sheet", "Jedes Blatt wird ein eigenes Formular"),
            (
                "all_sheets_one_form",
                "Alle ausgewaehlten Blaetter werden Abschnitte eines Formulars",
            ),
        ),
    )
    selected_sheets = forms.MultipleChoiceField(
        label="Blaetter",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    mapping_json = forms.CharField(
        label="Mapping JSON",
        widget=forms.Textarea(attrs={"rows": 22, "spellcheck": "false"}),
        help_text="Erkannte Felder und Tabellen koennen hier vor der Generierung bearbeitet werden.",
    )

    def __init__(self, *args, job, **kwargs):
        self.job = job
        initial = kwargs.pop("initial", {}) or {}
        mapping = job.mapping or {}
        initial.setdefault("mode", mapping.get("mode", "one_form_per_sheet"))
        initial.setdefault("selected_sheets", mapping.get("selected_sheets", []))
        initial.setdefault("mapping_json", mapping_to_pretty_json(mapping))
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        sheet_choices = [
            (sheet.get("name"), sheet.get("name"))
            for sheet in (job.analysis_result or {}).get("sheets", [])
            if sheet.get("name")
        ]
        self.fields["selected_sheets"].choices = sheet_choices

    def clean(self):
        cleaned = super().clean()
        raw_mapping = cleaned.get("mapping_json")
        if raw_mapping:
            try:
                mapping = parse_mapping_json(raw_mapping)
            except ValidationError as exc:
                self.add_error("mapping_json", exc)
            else:
                mapping["mode"] = cleaned.get("mode") or mapping.get("mode")
                mapping["selected_sheets"] = cleaned.get("selected_sheets") or []
                cleaned["mapping"] = mapping
        return cleaned
