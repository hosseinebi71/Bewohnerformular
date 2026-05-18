from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from form_builder.models import Field, Form, FormRecipient, FormSchedule
from form_builder.schedule_services import compute_next_run_at

DEFAULT_RECIPIENT = "formularstelle@example.local"

WEEKDAY_MAP = {
    "Montag": 0,
    "Dienstag": 1,
    "Mittwoch": 2,
    "Donnerstag": 3,
    "Freitag": 4,
    "Samstag": 5,
    "Sonntag": 6,
}

YES_NO_CHOICES = [{"value": "ja", "label": "Ja"}, {"value": "nein", "label": "Nein"}]

COMPLAINT_CHOICES = [
    {"value": "sozialbetreuung", "label": "Sozialbetreuung"},
    {"value": "kinderbetreuung", "label": "Kinderbetreuung"},
    {"value": "hausmeister", "label": "Hausmeister"},
    {"value": "sicherheit", "label": "Sicherheit"},
    {"value": "deutschkurs", "label": "Deutschkurs"},
    {"value": "bezirksregierung", "label": "Bezirksregierung"},
    {"value": "mensa", "label": "Mensa"},
    {"value": "schule", "label": "Schule"},
    {"value": "sonstiges", "label": "Sonstiges"},
]


BV_INCIDENT_CHOICES = [
    {"value": "-", "label": "-"},
    {"value": "Verd. COVID -19", "label": "Verd. COVID -19"},
    {"value": "Positiv. COVID -19", "label": "Positiv. COVID -19"},
    {"value": "Abschiebung", "label": "Abschiebung"},
    {"value": "Alkoholmissbrauch", "label": "Alkoholmissbrauch"},
    {"value": "Beleidigung", "label": "Beleidigung"},
    {"value": "Beschwerde über SDL", "label": "Beschwerde über SDL"},
    {"value": "Betrug/Betrugsdelikte", "label": "Betrug/Betrugsdelikte"},
    {"value": "Brand", "label": "Brand"},
    {"value": "Brandstiftung", "label": "Brandstiftung"},
    {"value": "Diebstahl", "label": "Diebstahl"},
    {"value": "Drogenfund", "label": "Drogenfund"},
    {"value": "Drogenmissbrauch", "label": "Drogenmissbrauch"},
    {"value": "Drohung", "label": "Drohung"},
    {"value": "Feueralarm/Fehlalarm", "label": "Feueralarm/Fehlalarm"},
    {"value": "Hausfriedensbruch", "label": "Hausfriedensbruch"},
    {"value": "Häusliche Gewalt", "label": "Häusliche Gewalt"},
    {"value": "Infektionskrankheiten", "label": "Infektionskrankheiten"},
    {"value": "Kindeswohlgefährdung", "label": "Kindeswohlgefährdung"},
    {"value": "Körperverletzung", "label": "Körperverletzung"},
    {"value": "Massenschlägerei", "label": "Massenschlägerei"},
    {"value": "Med. Notfall", "label": "Med. Notfall"},
    {"value": "Polizeiermittlungen", "label": "Polizeiermittlungen"},
    {"value": "Rassismus", "label": "Rassismus"},
    {"value": "Sachbeschädigung", "label": "Sachbeschädigung"},
    {"value": "Selbstverletzung", "label": "Selbstverletzung"},
    {"value": "Sexuelle Belästigung", "label": "Sexuelle Belästigung"},
    {"value": "Sexueller Übergriff", "label": "Sexueller Übergriff"},
    {"value": "Streit", "label": "Streit"},
    {"value": "Unfall", "label": "Unfall"},
    {"value": "Unruhestiftung", "label": "Unruhestiftung"},
    {"value": "Vandalismus", "label": "Vandalismus"},
    {"value": "Verdacht auf Terrorismus", "label": "Verdacht auf Terrorismus"},
    {"value": "Verstoß gegen Hausordnung", "label": "Verstoß gegen Hausordnung"},
    {"value": "Waffenfund", "label": "Waffenfund"},
]

BV_EINSATZ_CHOICES = [
    {"value": "-", "label": "-"},
    {"value": "Polizei", "label": "Polizei"},
    {"value": "Feuerwehr", "label": "Feuerwehr"},
    {"value": "Rettungswagen", "label": "Rettungswagen"},
    {"value": "SEK", "label": "SEK"},
    {"value": "Ordnungsamt", "label": "Ordnungsamt"},
    {"value": "Ausländerbehörden", "label": "Ausländerbehörden"},
]

BV_INFO_CHOICES = [
    {"value": "-", "label": "-"},
    {"value": "Gesundheitsamt", "label": "Gesundheitsamt"},
    {"value": "Polizei", "label": "Polizei"},
    {"value": "Feuerwehr", "label": "Feuerwehr"},
    {"value": "Rettungswagen", "label": "Rettungswagen"},
    {"value": "Ordnungsamt", "label": "Ordnungsamt"},
    {"value": "Auftraggeber", "label": "Auftraggeber"},
    {"value": "EHC HV", "label": "EHC HV"},
    {"value": "Jugendamt", "label": "Jugendamt"},
]

BV_VORGANG_CHOICES = [
    {"value": "-", "label": "-"},
    {"value": "Vorgang abgeschlossen", "label": "Vorgang abgeschlossen"},
    {"value": "Vorgang nicht abgeschlossen", "label": "Vorgang nicht abgeschlossen"},
    {"value": "BV folgt", "label": "BV folgt"},
]

FORMS = [
    {
        "key": "sozialticket-antrag",
        "title": "Sozialticket Antrag",
        "description": "Behördliche Antragstabelle mit sofortiger PDF-Vorschau im Tabellenlayout.",
        "dispatch": {"rhythm": "daily", "send_time": "05:00"},
        "fields": [
            ("datum", "Datum", Field.FieldType.DATE, False, {}),
            ("dias", "Dias", Field.FieldType.TEXT, False, {}),
            (
                "pkz",
                "PKZ",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "name",
                "Name",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "vorname",
                "Vorname",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "geb_am",
                "geb. am",
                Field.FieldType.DATE,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "geschlecht",
                "Geschlecht",
                Field.FieldType.SELECT,
                False,
                {
                    "choices": [
                        {"value": "weiblich", "label": "weiblich"},
                        {"value": "maennlich", "label": "maennlich"},
                        {"value": "divers", "label": "divers"},
                        {"value": "unbekannt", "label": "unbekannt"},
                    ]
                },
            ),
            ("grund", "Grund", Field.FieldType.TEXT, False, {"default_value": "Sozialticket"}),
        ],
    },
    {
        "key": "freiwillige-rueckkehr",
        "title": "Freiwillige Rückkehr",
        "description": "Sammelliste fuer Rueckkehr-Vorgaenge mit PKZ, Personendaten, DIAS, Datum und Restbetrag.",
        "dispatch": {"rhythm": "weekly", "weekday": "Freitag", "send_time": "08:00"},
        "fields": [
            (
                "pkz",
                "PKZ",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "name",
                "Name",
                Field.FieldType.TEXT,
                True,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "vorname",
                "Vorname",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "geb_am",
                "Geb.-Dat.",
                Field.FieldType.DATE,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            ("dias", "DIAS", Field.FieldType.TEXT, False, {}),
            ("datum", "Datum", Field.FieldType.DATE, False, {}),
            (
                "restbetrag_geld",
                "Restbar Geld",
                Field.FieldType.TEXT,
                False,
                {"placeholder": "z. B. 125,00 €"},
            ),
        ],
    },
    {
        "key": "bzr-woechentliche-sprechstunde",
        "title": "BZR wöchentliche Sprechstunde",
        "description": "Woechentliche Sprechstundenliste fuer Bezirksregierungstermine.",
        "dispatch": {"rhythm": "weekly", "weekday": "Freitag", "send_time": "07:30"},
        "fields": [
            ("ext", "EXT", Field.FieldType.TEXT, False, {}),
            (
                "pkz",
                "PKZ",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "name",
                "Name",
                Field.FieldType.TEXT,
                True,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "vorname",
                "Vorname",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            ("datum", "Datum", Field.FieldType.DATE, False, {}),
            ("uhrzeit", "Uhrzeit", Field.FieldType.TEXT, False, {"placeholder": "z. B. 10:30"}),
            ("grund", "Grund", Field.FieldType.TEXT, False, {}),
            ("sb_name", "SB Name", Field.FieldType.TEXT, False, {}),
        ],
    },
    {
        "key": "ab-sprechstundenliste",
        "title": "AB Sprechstundenliste",
        "description": "Sprechstundenliste fuer AB-Vorgaenge mit PKZ, Namen, Geburtsdatum und Grund.",
        "dispatch": {"rhythm": "weekly", "weekday": "Freitag", "send_time": "07:00"},
        "fields": [
            (
                "pkz",
                "PKZ",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "name",
                "Name",
                Field.FieldType.TEXT,
                True,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "vorname",
                "Vorname",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "geb_am",
                "Geb.Datum",
                Field.FieldType.DATE,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            ("grund", "Grund", Field.FieldType.TEXT, False, {}),
        ],
    },
    {
        "key": "zap-termin",
        "title": "ZAP Termin",
        "description": "Termin- und Vorgangserfassung fuer ZAP-Prozesse mit revisionsfaehiger PDF-Vorschau.",
        "dispatch": {"rhythm": "weekly", "weekday": "Freitag", "send_time": "07:00"},
        "fields": [
            ("datum", "Datum", Field.FieldType.DATE, True, {}),
            ("uhrzeit", "Uhrzeit", Field.FieldType.TEXT, False, {"placeholder": "z. B. 09:30"}),
            (
                "pkz",
                "PKZ",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "name",
                "Name",
                Field.FieldType.TEXT,
                True,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "vorname",
                "Vorname",
                Field.FieldType.TEXT,
                True,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "geb_am",
                "geb. am",
                Field.FieldType.DATE,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "anliegen",
                "Anliegen",
                Field.FieldType.TEXTAREA,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            ("bemerkung", "Bemerkung", Field.FieldType.TEXTAREA, False, {}),
        ],
    },
    {
        "key": "leistungsbescheid",
        "title": "Leistungsbescheid",
        "description": "Sammelliste fuer Leistungsbescheide bis zum Versand.",
        "dispatch": {"rhythm": "manual"},
        "fields": [
            ("datum", "Datum", Field.FieldType.DATE, False, {}),
            ("dias", "Dias", Field.FieldType.TEXT, False, {}),
            (
                "pkz",
                "PKZ",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "name",
                "Name",
                Field.FieldType.TEXT,
                True,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "vorname",
                "Vorname",
                Field.FieldType.TEXT,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "geb_am",
                "geb. am",
                Field.FieldType.DATE,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "grund",
                "Grund",
                Field.FieldType.SELECT,
                False,
                {
                    "choices": [
                        {"value": "bankkonto", "label": "Bankkonto"},
                        {"value": "anwalt", "label": "Anwalt"},
                        {"value": "integration", "label": "Integrationskurs"},
                        {"value": "sonstiges", "label": "Sonstiges"},
                    ]
                },
            ),
        ],
    },
    {
        "key": "meldung-besonderes-vorkommnis",
        "title": "Meldung Besonderes Vorkommnis (BV)",
        "description": "Sicherheitsrelevante BV-Meldung mit Ereignisart, Einsatz, Informationsweg und Sachverhalt.",
        "dispatch": {"rhythm": "manual"},
        "fields": [
            ("datum", "1. Datum", Field.FieldType.DATE, True, {}),
            (
                "einrichtung",
                "2. Einrichtung",
                Field.FieldType.TEXT,
                True,
                {"default_value": "ZUE - Weeze II"},
            ),
            ("lfd_nr", "3. LfdNr.", Field.FieldType.TEXT, False, {}),
            (
                "meldender",
                "4. Meldender (Name/Position)",
                Field.FieldType.TEXT,
                True,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "art_vorfall_1",
                "5. Art des Vorfalls 1",
                Field.FieldType.SELECT,
                False,
                {"choices": BV_INCIDENT_CHOICES, "default_value": "-"},
            ),
            (
                "art_vorfall_2",
                "5. Art des Vorfalls 2",
                Field.FieldType.SELECT,
                False,
                {"choices": BV_INCIDENT_CHOICES, "default_value": "-"},
            ),
            (
                "art_vorfall_3",
                "5. Art des Vorfalls 3",
                Field.FieldType.SELECT,
                False,
                {"choices": BV_INCIDENT_CHOICES, "default_value": "-"},
            ),
            ("sonstiges", "Sonstiges", Field.FieldType.BOOLEAN, False, {}),
            ("sonstiges_text", "Sonstiges - Erläuterung", Field.FieldType.TEXT, False, {}),
            ("zeit1", "6. Zeit 1", Field.FieldType.TEXT, False, {"placeholder": "z. B. 03:20"}),
            ("zeit2", "6. Zeit 2", Field.FieldType.TEXT, False, {}),
            ("zeit3", "6. Zeit 3", Field.FieldType.TEXT, False, {}),
            ("zeit4", "6. Zeit 4", Field.FieldType.TEXT, False, {}),
            ("zeit5", "6. Zeit 5", Field.FieldType.TEXT, False, {}),
            ("zeit6", "6. Zeit 6", Field.FieldType.TEXT, False, {}),
            ("zeit7", "6. Zeit 7", Field.FieldType.TEXT, False, {}),
            ("zeit8", "6. Zeit 8", Field.FieldType.TEXT, False, {}),
            (
                "sachverhalt",
                "6.1 Sachverhalt und Maßnahmen",
                Field.FieldType.TEXTAREA,
                True,
                {
                    "sensitivity": Field.SensitivityLevel.SENSITIVE,
                    "help_text": "Wer, was, wie, wo, warum und welche Maßnahmen wurden eingeleitet?",
                },
            ),
            (
                "taeter",
                "7.1 Täter",
                Field.FieldType.TEXTAREA,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "geschaedigte",
                "7.2 Geschädigte",
                Field.FieldType.TEXTAREA,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "zeugen",
                "7.3 Zeugen",
                Field.FieldType.TEXTAREA,
                False,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            (
                "einsatz_1",
                "8. Einsatz von 1",
                Field.FieldType.SELECT,
                False,
                {"choices": BV_EINSATZ_CHOICES, "default_value": "-"},
            ),
            (
                "einsatz_2",
                "8. Einsatz von 2",
                Field.FieldType.SELECT,
                False,
                {"choices": BV_EINSATZ_CHOICES, "default_value": "-"},
            ),
            (
                "einsatz_3",
                "8. Einsatz von 3",
                Field.FieldType.SELECT,
                False,
                {"choices": BV_EINSATZ_CHOICES, "default_value": "-"},
            ),
            (
                "info_1",
                "9. Wer wurde informiert 1",
                Field.FieldType.SELECT,
                False,
                {"choices": BV_INFO_CHOICES, "default_value": "-"},
            ),
            (
                "info_2",
                "9. Wer wurde informiert 2",
                Field.FieldType.SELECT,
                False,
                {"choices": BV_INFO_CHOICES, "default_value": "-"},
            ),
            (
                "info_3",
                "9. Wer wurde informiert 3",
                Field.FieldType.SELECT,
                False,
                {"choices": BV_INFO_CHOICES, "default_value": "-"},
            ),
            (
                "vorgang",
                "10. Vorgang",
                Field.FieldType.SELECT,
                True,
                {"choices": BV_VORGANG_CHOICES, "default_value": "-"},
            ),
        ],
    },
    {
        "key": "beschwerdebogen-zue-weeze",
        "title": "Beschwerdebogen ZUE-Weeze II",
        "description": "Beschwerdeaufnahme mit Kategorien, Freitext und Unterschriftsfeldern.",
        "dispatch": {"rhythm": "manual"},
        "fields": [
            (
                "beschwerde_von",
                "Beschwerde von",
                Field.FieldType.TEXT,
                True,
                {"sensitivity": Field.SensitivityLevel.SENSITIVE},
            ),
            ("datum", "Datum", Field.FieldType.DATE, False, {}),
            (
                "beschwerde_ueber",
                "Beschwerde über",
                Field.FieldType.MULTISELECT,
                False,
                {"choices": COMPLAINT_CHOICES},
            ),
            (
                "erlaeuterung",
                "Erläuterung",
                Field.FieldType.TEXTAREA,
                False,
                {
                    "sensitivity": Field.SensitivityLevel.SENSITIVE,
                    "help_text": "Sachliche Beschreibung der Beschwerde.",
                },
            ),
            (
                "unterschrift_beschwerdefuehrer",
                "Unterschrift Beschwerdeführer",
                Field.FieldType.TEXT,
                False,
                {"ui_config": {"widget": "signature"}},
            ),
            (
                "unterschrift_aufnehmer",
                "Unterschrift Beschwerdeaufnehmer",
                Field.FieldType.TEXT,
                False,
                {"ui_config": {"widget": "signature"}},
            ),
        ],
    },
]


class Command(BaseCommand):
    help = "Create professional demo forms for government-style workflows."

    def add_arguments(self, parser):
        parser.add_argument("--recipient", default=DEFAULT_RECIPIENT)

    def handle(self, *args, **options):
        user = self._get_user()
        with transaction.atomic():
            for spec in FORMS:
                form = self._upsert_form(spec, user)
                form.publish()
                schema = form.sync_schema()
                schema["dispatch"] = spec.get("dispatch", {"rhythm": "manual"})
                schema["pdf_layout"] = spec.get("key")
                form.schema = schema
                form.save(update_fields=["schema", "updated_at"])
                recipient = self._upsert_recipient(form, options["recipient"], user)
                self._upsert_schedule(form, spec.get("dispatch", {}), user, recipient)
                self.stdout.write(
                    self.style.SUCCESS(f"{form.title} wurde angelegt/veroeffentlicht.")
                )
        self.stdout.write(self.style.SUCCESS("Fertig. Oeffnen: http://127.0.0.1:8000/formulare/"))

    def _upsert_form(self, spec, user):
        form, _ = Form.objects.get_or_create(
            key=spec["key"],
            version=1,
            defaults={
                "title": spec["title"],
                "description": spec["description"],
                "status": Form.PublicationStatus.DRAFT,
                "review_required": False,
                "is_archivable": True,
                "retention_period_days": 3650,
                "created_by": user,
                "updated_by": user,
            },
        )
        form.title = spec["title"]
        form.description = spec["description"]
        form.review_required = False
        form.is_archivable = True
        form.retention_period_days = 3650
        form.updated_by = user
        if form.status == Form.PublicationStatus.PUBLISHED:
            form.status = Form.PublicationStatus.DRAFT
        form.save()

        active_keys = {item[0] for item in spec["fields"]}

        # The seed command must be safe to run repeatedly on an existing local
        # database. Older versions of a form may already contain fields at the
        # same positions as the new specification. Move *all* existing fields to
        # a temporary high, unique position range first, then write the active
        # specification back to positions 1..n. This avoids SQLite unique
        # constraint collisions on (form, position).
        existing_fields = list(form.fields.order_by("position", "key", "id"))
        max_position = max([field.position for field in existing_fields], default=0)
        temporary_base = max_position + 1000
        for offset, existing_field in enumerate(existing_fields, start=1):
            existing_field.position = temporary_base + offset
            existing_field.is_active = existing_field.key in active_keys
            existing_field.updated_by = user
            existing_field.save(update_fields=["position", "is_active", "updated_by", "updated_at"])

        for position, (key, label, field_type, required, extra) in enumerate(
            spec["fields"], start=1
        ):
            field = form.fields.filter(key=key).first()
            if field is None:
                field = Field(form=form, key=key, created_by=user)
            field.position = position
            field.label = label
            field.field_type = field_type
            field.required = required
            field.sensitivity = extra.get("sensitivity", Field.SensitivityLevel.NORMAL)
            field.placeholder = extra.get("placeholder", "")
            field.help_text = extra.get("help_text", "")
            field.default_value = extra.get("default_value")
            field.choices = extra.get("choices", [])
            field.validation_rules = extra.get("validation_rules", {})
            field.ui_config = {
                "source": "seed_government_demo_forms",
                "pdf_layout": spec["key"],
                **(extra.get("ui_config", {}) or {}),
            }
            field.is_active = True
            field.updated_by = user
            field.save()
        return form

    @staticmethod
    def _upsert_recipient(form, email, user):
        dispatch = (form.schema or {}).get("dispatch", {})
        lookup = {
            "form": form,
            "email": email,
            "recipient_type": FormRecipient.RecipientType.TO,
            "channel": FormRecipient.ChannelType.SMTP,
        }
        defaults = {
            "name": "Formularstelle",
            "is_active": True,
            "is_default": True,
            "subject_template": "{form} - {name} {vorname}",
            "body_template": "Anbei erhalten Sie das Formular {form} als PDF.",
            "dispatch_frequency": dispatch.get("rhythm", "manual"),
            "dispatch_time": dispatch.get("send_time") or None,
            "dispatch_weekday": (
                WEEKDAY_MAP.get(dispatch.get("weekday", "Montag"), 0)
                if dispatch.get("rhythm") == "weekly"
                else None
            ),
            "updated_by": user,
        }
        recipient, created = FormRecipient.objects.update_or_create(
            **lookup,
            defaults={**defaults, "created_by": user},
        )

        # Keep older demo recipients with the same form harmless, but never rewrite
        # their email address. Rewriting a default recipient to another existing
        # e-mail caused UNIQUE(form, email, recipient_type, channel) failures on
        # already seeded databases.
        FormRecipient.objects.filter(form=form, name="Formularstelle").exclude(
            pk=recipient.pk
        ).update(
            is_default=False,
            updated_by=user,
        )
        return recipient

    @staticmethod
    def _upsert_schedule(form, dispatch, user, recipient=None):
        rhythm = dispatch.get("rhythm", "manual")
        if rhythm not in {"daily", "weekly"}:
            return None
        run_time = dispatch.get("send_time", "05:00" if rhythm == "daily" else "07:00")
        weekday = WEEKDAY_MAP.get(dispatch.get("weekday", "Montag"), 0)
        config = {
            "frequency": rhythm,
            "weekday": weekday,
            "run_time": run_time,
            "source": "seed_government_demo_forms",
            "recipient_ids": [str(recipient.pk)] if recipient else [],
        }
        name = f"Standardversand - {form.title}"
        schedule, _ = FormSchedule.objects.update_or_create(
            form=form,
            name=name,
            defaults={
                "trigger_type": FormSchedule.TriggerType.SCHEDULED,
                "status": FormSchedule.ScheduleStatus.ACTIVE,
                "timezone": "Europe/Berlin",
                "cron_expression": (
                    f"{rhythm} {run_time}"
                    if rhythm == "daily"
                    else f"weekly weekday={weekday} {run_time}"
                ),
                "start_at": None,
                "end_at": None,
                "last_run_at": None,
                "is_active": True,
                "config": config,
                "created_by": user,
                "updated_by": user,
            },
        )
        schedule.next_run_at = compute_next_run_at(schedule, from_time=timezone.now())
        schedule.save(update_fields=["next_run_at", "updated_at"])
        if recipient:
            schedule.recipients.set([recipient])
            config = dict(schedule.config or {})
            config["recipient_ids"] = [str(recipient.pk)]
            schedule.config = config
            schedule.save(update_fields=["config", "updated_at"])
        return schedule

    @staticmethod
    def _get_user():
        User = get_user_model()
        return User.objects.filter(is_superuser=True).order_by("id").first()
