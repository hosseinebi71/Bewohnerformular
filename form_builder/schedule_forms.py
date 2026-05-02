from django import forms
from django.utils import timezone

from .models import Form, FormSchedule
from .schedule_services import compute_next_run_at

FREQUENCY_CHOICES = [("daily", "Taeglich"), ("weekly", "Woechentlich")]
WEEKDAY_CHOICES = [("0", "Montag"), ("1", "Dienstag"), ("2", "Mittwoch"), ("3", "Donnerstag"), ("4", "Freitag"), ("5", "Samstag"), ("6", "Sonntag")]

class FormScheduleForm(forms.ModelForm):
    frequency = forms.ChoiceField(choices=FREQUENCY_CHOICES, label="Rhythmus")
    weekday = forms.ChoiceField(choices=WEEKDAY_CHOICES, required=False, label="Wochentag")
    run_time = forms.TimeField(label="Uhrzeit", widget=forms.TimeInput(attrs={"type": "time"}))

    class Meta:
        model = FormSchedule
        fields = ("name", "form", "status", "is_active", "timezone", "start_at", "end_at")
        labels = {"name":"Name", "form":"Formular", "status":"Status", "is_active":"Aktiv", "timezone":"Zeitzone", "start_at":"Start ab", "end_at":"Ende bis"}
        widgets = {"start_at": forms.DateTimeInput(attrs={"type":"datetime-local"}), "end_at": forms.DateTimeInput(attrs={"type":"datetime-local"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["form"].queryset = Form.objects.filter(status=Form.PublicationStatus.PUBLISHED).order_by("title", "version")
        self.fields["timezone"].initial = self.fields["timezone"].initial or "Europe/Berlin"
        self.fields["status"].initial = FormSchedule.ScheduleStatus.ACTIVE
        self.fields["is_active"].initial = True
        if self.instance and self.instance.pk:
            config = self.instance.config or {}
            self.fields["frequency"].initial = config.get("frequency", "weekly")
            self.fields["weekday"].initial = str(config.get("weekday", 0))
            self.fields["run_time"].initial = config.get("run_time", "08:00")

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("frequency") == "weekly" and cleaned_data.get("weekday") in (None, ""):
            self.add_error("weekday", "Bitte fuer woechentliche Zeitplaene einen Wochentag auswaehlen.")
        return cleaned_data

    def save(self, commit=True):
        schedule = super().save(commit=False)
        run_time = self.cleaned_data["run_time"]
        config = dict(schedule.config or {})
        config.update({"frequency": self.cleaned_data["frequency"], "weekday": int(self.cleaned_data.get("weekday") or 0), "run_time": run_time.strftime("%H:%M")})
        schedule.config = config
        schedule.trigger_type = FormSchedule.TriggerType.SCHEDULED
        schedule.cron_expression = self._build_human_cron(config)
        schedule.next_run_at = compute_next_run_at(schedule, from_time=timezone.now())
        if commit:
            schedule.save()
        return schedule

    @staticmethod
    def _build_human_cron(config):
        time_value = config.get("run_time", "08:00")
        if config.get("frequency") == "daily":
            return f"daily {time_value}"
        return f"weekly weekday={config.get('weekday', 0)} {time_value}"
