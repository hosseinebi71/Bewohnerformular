from django import forms
from django.contrib.auth import get_user_model

from .models import Form, FormRecipient, UserAccessProfile


class FormRecipientAdminForm(forms.ModelForm):
    class Meta:
        model = FormRecipient
        fields = "__all__"


class FormRecipientSettingsForm(forms.ModelForm):
    class Meta:
        model = FormRecipient
        fields = (
            "form",
            "name",
            "email",
            "recipient_type",
            "channel",
            "is_default",
            "is_active",
            "dispatch_frequency",
            "dispatch_weekday",
            "dispatch_time",
            "subject_template",
            "body_template",
        )
        labels = {
            "form": "Formular",
            "name": "Name / Stelle",
            "email": "E-Mail",
            "recipient_type": "Typ",
            "channel": "Kanal",
            "is_default": "Standardziel",
            "is_active": "Aktiv",
            "dispatch_frequency": "Rhythmus",
            "dispatch_weekday": "Wochentag",
            "dispatch_time": "Uhrzeit",
            "subject_template": "Betreff",
            "body_template": "Text",
        }
        widgets = {
            "dispatch_time": forms.TimeInput(attrs={"type": "time"}),
            "body_template": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["form"].queryset = Form.objects.filter(
            status=Form.PublicationStatus.PUBLISHED
        ).order_by("title", "version")
        self.fields["dispatch_frequency"].required = False
        self.fields["dispatch_weekday"].required = False
        self.fields["dispatch_time"].required = False
        self.fields["name"].required = False
        self.fields["subject_template"].required = False
        self.fields["body_template"].required = False
        self.fields["dispatch_weekday"].widget = forms.Select(
            choices=[("", "-")]
            + [
                (0, "Montag"),
                (1, "Dienstag"),
                (2, "Mittwoch"),
                (3, "Donnerstag"),
                (4, "Freitag"),
                (5, "Samstag"),
                (6, "Sonntag"),
            ]
        )

    def clean(self):
        cleaned = super().clean()
        frequency = cleaned.get("dispatch_frequency") or "manual"
        if frequency == "weekly" and cleaned.get("dispatch_weekday") in (None, ""):
            self.add_error("dispatch_weekday", "Bitte einen Wochentag auswaehlen.")
        return cleaned


class UserAccessProfileForm(forms.ModelForm):
    class Meta:
        model = UserAccessProfile
        fields = (
            "user",
            "is_active",
            "scope_mode",
            "org_units",
            "allowed_form_keys",
            "can_dashboard",
            "can_forms",
            "can_create",
            "can_send",
            "can_archive",
            "can_settings",
            "can_manage_settings",
        )
        labels = {
            "user": "Mitarbeiter",
            "is_active": "Aktiv",
            "scope_mode": "Datenbereich",
            "org_units": "Organisationseinheiten",
            "allowed_form_keys": "Erlaubte Formularfamilien",
            "can_dashboard": "Dashboard",
            "can_forms": "Formulare",
            "can_create": "Vorgaenge erstellen",
            "can_send": "Schicken / Versand",
            "can_archive": "Archiv",
            "can_settings": "Einstellungen sehen",
            "can_manage_settings": "Einstellungen verwalten",
        }
        widgets = {
            "can_dashboard": forms.CheckboxInput,
            "org_units": forms.Textarea(
                attrs={"rows": 2, "placeholder": '["weeze", "duesseldorf"]'}
            ),
            "allowed_form_keys": forms.Textarea(
                attrs={"rows": 2, "placeholder": '["sozialticket-antrag"]'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("username")
