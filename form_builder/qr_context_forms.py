from __future__ import annotations

import json

from django import forms

from .models import Bewohner, Form
from .qr_context_models import QRFormContext


class QRFormContextForm(forms.ModelForm):
    context_payload_text = forms.CharField(
        required=False,
        label="Kontextdaten JSON",
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": '{"bereich": "Kueche"}'}),
        help_text="Optional: nicht sensible Vorbelegungen als JSON-Objekt.",
    )

    class Meta:
        model = QRFormContext
        fields = [
            "form",
            "bewohner",
            "label",
            "context_type",
            "context_key",
            "expires_at",
            "is_active",
        ]
        widgets = {
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["form"].queryset = Form.objects.filter(
            status=Form.PublicationStatus.PUBLISHED
        ).order_by("title")
        self.fields["bewohner"].queryset = Bewohner.objects.filter(
            status=Bewohner.RecordStatus.ACTIVE
        ).order_by("last_name", "first_name")
        self.fields["bewohner"].required = False
        if self.instance and self.instance.pk:
            self.fields["context_payload_text"].initial = json.dumps(
                self.instance.context_payload or {},
                ensure_ascii=False,
                indent=2,
            )

    def clean_context_payload_text(self):
        value = self.cleaned_data.get("context_payload_text", "").strip()
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Bitte gueltiges JSON eingeben.") from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError("Kontextdaten muessen ein JSON-Objekt sein.")
        return parsed

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.context_payload = self.cleaned_data.get("context_payload_text") or {}
        if commit:
            instance.save()
        return instance
