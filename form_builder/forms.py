from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as ModelValidationError
from django.forms.models import construct_instance

from .models import Field, Form, FormRecipient, FormSection, UserAccessProfile


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


class FormBuilderMetadataForm(forms.ModelForm):
    class Meta:
        model = Form
        fields = (
            "key",
            "version",
            "title",
            "description",
            "org_unit",
            "status",
            "review_required",
            "is_archivable",
            "retention_period_days",
        )
        labels = {
            "key": "Formular-Key",
            "version": "Version",
            "title": "Titel",
            "description": "Beschreibung",
            "org_unit": "Organisationseinheit",
            "status": "Status",
            "review_required": "Review erforderlich",
            "is_archivable": "Archivfaehig",
            "retention_period_days": "Aufbewahrung in Tagen",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "key": "Stabiler technischer Key, z. B. hygiene-kontrolle.",
            "version": "Fortlaufende Version innerhalb derselben Formularfamilie.",
            "org_unit": "Optionaler Standort-/Abteilungscode fuer Berechtigungen.",
        }


class FormSectionBuilderForm(forms.ModelForm):
    def __init__(self, *args, form_definition: Form | None = None, **kwargs):
        self.form_definition = form_definition or getattr(kwargs.get("instance"), "form", None)
        super().__init__(*args, **kwargs)
        self.fields["is_active"].required = False

    class Meta:
        model = FormSection
        fields = ("position", "title", "description", "is_collapsible", "is_active")
        labels = {
            "position": "Reihenfolge",
            "title": "Titel",
            "description": "Hilfetext/Beschreibung",
            "is_collapsible": "Einklappbar",
            "is_active": "Aktiv",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_position(self):
        position = self.cleaned_data.get("position")
        if not position or not self.form_definition:
            return position
        duplicate = FormSection.objects.filter(
            form=self.form_definition,
            position=position,
        )
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError(
                "Diese Reihenfolge ist in diesem Formular bereits vergeben."
            )
        return position


class FieldBuilderForm(forms.ModelForm):
    FIELD_KIND_TEXT = Field.FieldType.TEXT
    FIELD_KIND_TEXTAREA = Field.FieldType.TEXTAREA
    FIELD_KIND_NUMBER = "number"
    FIELD_KIND_DATE = Field.FieldType.DATE
    FIELD_KIND_BOOLEAN = Field.FieldType.BOOLEAN
    FIELD_KIND_SELECT = Field.FieldType.SELECT
    FIELD_KIND_FILE = Field.FieldType.FILE
    FIELD_KIND_SIGNATURE = "signature"

    FIELD_KIND_CHOICES = (
        (FIELD_KIND_TEXT, "Text"),
        (FIELD_KIND_TEXTAREA, "Mehrzeilig"),
        (FIELD_KIND_NUMBER, "Zahl"),
        (Field.FieldType.INTEGER, "Ganzzahl"),
        (Field.FieldType.DECIMAL, "Dezimalzahl"),
        (FIELD_KIND_DATE, "Datum"),
        (Field.FieldType.DATETIME, "Datum und Uhrzeit"),
        (FIELD_KIND_BOOLEAN, "Checkbox / Ja-Nein"),
        (FIELD_KIND_SELECT, "Auswahl"),
        (Field.FieldType.MULTISELECT, "Mehrfachauswahl"),
        (Field.FieldType.RADIO, "Radiogruppe"),
        (Field.FieldType.EMAIL, "E-Mail"),
        (Field.FieldType.PHONE, "Telefon"),
        (FIELD_KIND_FILE, "Datei"),
        (FIELD_KIND_SIGNATURE, "Unterschrift"),
    )

    field_type = forms.ChoiceField(choices=FIELD_KIND_CHOICES, label="Feldtyp")
    choices_text = forms.CharField(
        required=False,
        label="Auswahlwerte",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=(
            "Nur fuer Auswahlfelder. Eine Option pro Zeile, entweder 'wert|Label' oder nur 'Label'."
        ),
    )

    class Meta:
        model = Field
        fields = (
            "section",
            "position",
            "key",
            "label",
            "field_type",
            "required",
            "help_text",
            "placeholder",
            "choices_text",
            "is_active",
        )
        labels = {
            "section": "Abschnitt",
            "position": "Reihenfolge",
            "key": "Technischer Name",
            "label": "Label",
            "required": "Pflichtfeld",
            "help_text": "Hilfetext",
            "placeholder": "Platzhalter",
            "is_active": "Aktiv",
        }
        widgets = {
            "help_text": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "key": "Stabiler Feld-Key ohne Leerzeichen, z. B. kontrollpunkt.",
            "position": "Reihenfolge innerhalb des gewaehlten Abschnitts oder der globalen Felder.",
        }

    def __init__(self, *args, form_definition: Form, **kwargs):
        self.form_definition = form_definition
        super().__init__(*args, **kwargs)
        self.fields["section"].queryset = form_definition.sections.filter(is_active=True).order_by(
            "position", "title"
        )
        self.fields["section"].required = False
        self.fields["is_active"].required = False

        if not self.instance.pk:
            self.fields["position"].initial = self._next_position()
            return

        self.fields["field_type"].initial = self._initial_field_kind()
        self.fields["choices_text"].initial = self._choices_as_text()

    def _selected_section_for_position(self):
        section_id = (
            self.data.get("section")
            if self.is_bound
            else self.initial.get("section") or getattr(self.instance, "section_id", None)
        )
        if not section_id:
            return None
        try:
            return self.form_definition.sections.get(pk=section_id)
        except (FormSection.DoesNotExist, ValueError, TypeError):
            return None

    def _next_position(self) -> int:
        selected_section = self._selected_section_for_position()
        fields = self.form_definition.fields.all()
        if selected_section:
            fields = fields.filter(section=selected_section)
        else:
            fields = fields.filter(section__isnull=True)
        positions = list(fields.values_list("position", flat=True))
        return (max(positions) + 1) if positions else 1

    def _initial_field_kind(self) -> str:
        ui_config = self.instance.ui_config or {}
        if ui_config.get("widget") == "signature":
            return self.FIELD_KIND_SIGNATURE
        return self.instance.field_type

    def _choices_as_text(self) -> str:
        lines = []
        for choice in self.instance.choices or []:
            value = choice.get("value", "")
            label = choice.get("label", value)
            lines.append(f"{value}|{label}" if value != label else str(label))
        return "\n".join(lines)

    def clean_section(self):
        section = self.cleaned_data.get("section")
        if section and section.form_id != self.form_definition.pk:
            raise forms.ValidationError("Dieser Abschnitt gehoert nicht zu diesem Formular.")
        return section

    def clean_field_type(self):
        field_kind = self.cleaned_data.get("field_type")
        self._selected_field_kind = field_kind
        return self._model_field_type(field_kind)

    def clean_choices_text(self):
        raw = self.cleaned_data.get("choices_text", "")
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
            if not value or not label:
                raise forms.ValidationError("Auswahlwerte muessen Wert und Label enthalten.")
            choices.append({"value": value, "label": label})
        return choices

    def clean(self):
        cleaned = super().clean()
        field_kind = getattr(self, "_selected_field_kind", None) or self.data.get("field_type")
        choices = cleaned.get("choices_text") or []
        model_field_type = self._model_field_type(field_kind)
        if model_field_type in Field.CHOICE_FIELD_TYPES and not choices:
            self.add_error("choices_text", "Auswahlfelder brauchen mindestens einen Eintrag.")
        if model_field_type not in Field.CHOICE_FIELD_TYPES:
            cleaned["choices_text"] = []

        position = cleaned.get("position")
        section = cleaned.get("section")
        if position:
            duplicate = Field.objects.filter(form=self.form_definition, position=position)
            if section:
                duplicate = duplicate.filter(section=section)
            else:
                duplicate = duplicate.filter(section__isnull=True)
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error(
                    "position",
                    "Diese Reihenfolge ist in diesem Abschnitt bereits vergeben.",
                )
        return cleaned

    def _model_field_type(self, field_kind: str | None) -> str:
        if field_kind == self.FIELD_KIND_NUMBER:
            return Field.FieldType.INTEGER
        if field_kind == self.FIELD_KIND_SIGNATURE:
            return Field.FieldType.TEXT
        return field_kind or Field.FieldType.TEXT

    def _apply_derived_model_values(self) -> None:
        field_kind = getattr(self, "_selected_field_kind", None) or self.data.get("field_type")
        self.instance.form = self.form_definition
        self.instance.field_type = self._model_field_type(field_kind)
        self.instance.choices = self.cleaned_data.get("choices_text") or []
        ui_config = dict(self.instance.ui_config or {})
        if field_kind == self.FIELD_KIND_SIGNATURE:
            ui_config["widget"] = "signature"
        else:
            ui_config.pop("widget", None)
        self.instance.ui_config = ui_config

    def _post_clean(self):
        opts = self._meta
        exclude = self._get_validation_exclusions()
        try:
            self.instance = construct_instance(self, self.instance, opts.fields, opts.exclude)
            self._apply_derived_model_values()
        except ModelValidationError as exc:
            self._update_errors(exc)
        try:
            self.instance.full_clean(exclude=exclude, validate_unique=False)
        except ModelValidationError as exc:
            self._update_errors(exc)
        if self._validate_unique:
            self.validate_unique()

    def save(self, commit=True):
        instance = super().save(commit=False)
        self._apply_derived_model_values()
        if commit:
            instance.save()
        return instance


class ConfirmDeleteForm(forms.Form):
    confirm = forms.BooleanField(required=False, widget=forms.HiddenInput, initial=True)
