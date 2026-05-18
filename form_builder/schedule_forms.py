from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Form, FormRecipient, FormSchedule
from .schedule_services import compute_next_run_at

FREQUENCY_CHOICES = [
    ("manual", "Manuell"),
    ("daily", "Taeglich"),
    ("weekly", "Woechentlich"),
]
WEEKDAY_CHOICES = [
    ("0", "Montag"),
    ("1", "Dienstag"),
    ("2", "Mittwoch"),
    ("3", "Donnerstag"),
    ("4", "Freitag"),
    ("5", "Samstag"),
    ("6", "Sonntag"),
]


class FormScheduleForm(forms.ModelForm):
    frequency = forms.ChoiceField(choices=FREQUENCY_CHOICES, label="Rhythmus")
    weekday = forms.ChoiceField(choices=WEEKDAY_CHOICES, required=False, label="Wochentag")
    run_time = forms.TimeField(
        label="Uhrzeit",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    recipients = forms.ModelMultipleChoiceField(
        queryset=FormRecipient.objects.none(),
        required=False,
        label="E-Mail-Ziele",
        help_text="Nur aktive E-Mail-Ziele des ausgewaehlten Formulars. Automatische Zeitplaene brauchen mindestens ein Ziel.",
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = FormSchedule
        fields = ("name", "form", "status", "is_active", "timezone", "start_at", "end_at")
        labels = {
            "name": "Interner Name",
            "form": "Formular",
            "status": "Status",
            "is_active": "Aktiv",
            "timezone": "Zeitzone",
            "start_at": "Start ab",
            "end_at": "Ende bis",
        }
        widgets = {
            "name": forms.HiddenInput(),
            "status": forms.HiddenInput(),
            "timezone": forms.HiddenInput(),
            "start_at": forms.HiddenInput(),
            "end_at": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False
        self.fields["status"].required = False
        self.fields["timezone"].required = False
        self.fields["start_at"].required = False
        self.fields["end_at"].required = False
        self.fields["timezone"].initial = "Europe/Berlin"
        self.fields["status"].initial = FormSchedule.ScheduleStatus.ACTIVE
        self.fields["start_at"].initial = None
        self.fields["end_at"].initial = None
        self.fields["form"].queryset = Form.objects.filter(
            status=Form.PublicationStatus.PUBLISHED
        ).order_by("title", "version")
        self.fields["is_active"].initial = True

        selected_form = self.instance.form if self.instance and self.instance.pk else None
        posted_form_id = self.data.get("form") if self.is_bound else None
        if posted_form_id:
            try:
                selected_form = Form.objects.get(pk=posted_form_id)
            except (Form.DoesNotExist, ValidationError, ValueError):
                pass

        if selected_form:
            self.fields["recipients"].queryset = FormRecipient.objects.filter(
                form=selected_form,
                is_active=True,
            ).order_by("recipient_type", "email")
        else:
            self.fields["recipients"].queryset = FormRecipient.objects.filter(
                is_active=True
            ).order_by("form__title", "recipient_type", "email")

        if self.instance and self.instance.pk:
            config = self.instance.config or {}
            self.fields["frequency"].initial = config.get("frequency", "manual")
            self.fields["weekday"].initial = str(config.get("weekday", 0))
            self.fields["run_time"].initial = config.get("run_time") or ""
            linked_recipients = list(self.instance.recipients.values_list("pk", flat=True))
            if linked_recipients:
                self.fields["recipients"].initial = linked_recipients
            elif config.get("recipient_ids"):
                self.fields["recipients"].initial = config.get("recipient_ids")
        else:
            self.fields["frequency"].initial = "manual"

    def clean(self):
        cleaned_data = super().clean()
        form = cleaned_data.get("form")
        frequency = cleaned_data.get("frequency") or "manual"
        recipients = cleaned_data.get("recipients")

        if frequency == "weekly" and cleaned_data.get("weekday") in (None, ""):
            self.add_error(
                "weekday", "Bitte fuer woechentliche Zeitplaene einen Wochentag auswaehlen."
            )
        if frequency != "manual" and not cleaned_data.get("run_time"):
            self.add_error(
                "run_time", "Bitte eine Uhrzeit fuer automatische Versandplanung angeben."
            )
        if frequency != "manual" and not recipients:
            self.add_error(
                "recipients", "Bitte mindestens ein E-Mail-Ziel fuer diesen Zeitplan auswaehlen."
            )
        if form and recipients:
            invalid = [recipient for recipient in recipients if recipient.form_id != form.id]
            if invalid:
                self.add_error(
                    "recipients", "E-Mail-Ziele muessen zum ausgewaehlten Formular gehoeren."
                )
        return cleaned_data

    def save(self, commit=True):
        schedule = super().save(commit=False)
        run_time = self.cleaned_data.get("run_time")
        frequency = self.cleaned_data.get("frequency") or "manual"
        config = dict(schedule.config or {})
        config.update(
            {
                "frequency": frequency,
                "weekday": int(self.cleaned_data.get("weekday") or 0),
                "run_time": run_time.strftime("%H:%M") if run_time else "",
                "recipient_ids": [str(obj.pk) for obj in self.cleaned_data.get("recipients", [])],
            }
        )
        schedule.config = config
        schedule.name = schedule.name or f"Standardversand - {schedule.form.title}"
        if not schedule.name.startswith("Standardversand -"):
            schedule.name = f"Standardversand - {schedule.form.title}"
        schedule.status = FormSchedule.ScheduleStatus.ACTIVE
        schedule.is_active = bool(self.cleaned_data.get("is_active", True))
        schedule.timezone = "Europe/Berlin"
        schedule.start_at = None
        schedule.end_at = None
        schedule.trigger_type = (
            FormSchedule.TriggerType.MANUAL
            if frequency == "manual"
            else FormSchedule.TriggerType.SCHEDULED
        )
        schedule.cron_expression = self._build_human_cron(config)
        schedule.next_run_at = (
            None
            if frequency == "manual"
            else compute_next_run_at(schedule, from_time=timezone.now())
        )
        if commit:
            schedule.save()
            self.save_recipients(schedule)
        return schedule

    def save_recipients(self, schedule: FormSchedule) -> None:
        recipients = list(self.cleaned_data.get("recipients", []))
        schedule.recipients.set(recipients)
        config = dict(schedule.config or {})
        config["recipient_ids"] = [str(obj.pk) for obj in recipients]
        FormSchedule.objects.filter(pk=schedule.pk).update(config=config, updated_at=timezone.now())

    @staticmethod
    def _build_human_cron(config):
        time_value = config.get("run_time", "") or "manuell"
        if config.get("frequency") == "manual":
            return "manual"
        if config.get("frequency") == "daily":
            return f"daily {time_value}"
        return f"weekly weekday={config.get('weekday', 0)} {time_value}"
