import hashlib
import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserStampedModel(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_updated",
    )

    class Meta:
        abstract = True


class UUIDPrimaryKeyModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class UserAccessProfile(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="form_access_profile",
    )

    class ScopeMode(models.TextChoices):
        ALL = "all", "Alle zulaessigen Daten"
        ORG_UNITS = "org_units", "Nur Organisationseinheiten"
        OWN = "own", "Nur eigene Vorgaenge"

    scope_mode = models.CharField(
        max_length=16,
        choices=ScopeMode.choices,
        default=ScopeMode.OWN,
        db_index=True,
        verbose_name="Datenbereich",
        help_text="Begrenzt Formulare, Bewohner, PDFs, Ausgangskorb und Archiv auf einen organisatorischen Bereich.",
    )
    org_units = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Organisationseinheiten",
        help_text="Liste stabiler Codes, z. B. Standort/Abteilung. Leer bedeutet: kein Organisationsbereich.",
    )
    allowed_form_keys = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Erlaubte Formularfamilien",
        help_text="Optionale Liste von Formular-Keys. Leer bedeutet: alle Formularfamilien im Datenbereich.",
    )
    can_dashboard = models.BooleanField(default=True, verbose_name="Dashboard sehen")
    can_forms = models.BooleanField(default=True, verbose_name="Formulare sehen")
    can_create = models.BooleanField(default=True, verbose_name="Vorgaenge erstellen")
    can_send = models.BooleanField(default=True, verbose_name="Schicken / Versand")
    can_archive = models.BooleanField(default=True, verbose_name="Archiv sehen")
    can_settings = models.BooleanField(default=False, verbose_name="Einstellungen sehen")
    can_manage_settings = models.BooleanField(default=False, verbose_name="Einstellungen verwalten")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")

    class Meta:
        verbose_name = "Mitarbeiter-Zugriff"
        verbose_name_plural = "Mitarbeiter-Zugriffe"

    def clean(self) -> None:
        errors = {}
        if not isinstance(self.org_units, list):
            errors["org_units"] = "Organisationseinheiten muessen als Liste gespeichert werden."
        if not isinstance(self.allowed_form_keys, list):
            errors["allowed_form_keys"] = "Formularfamilien muessen als Liste gespeichert werden."
        if errors:
            raise ValidationError(errors)

    def normalized_org_units(self) -> list[str]:
        if not isinstance(self.org_units, list):
            return []
        return [str(item).strip() for item in self.org_units if str(item).strip()]

    def normalized_form_keys(self) -> list[str]:
        if not isinstance(self.allowed_form_keys, list):
            return []
        return [str(item).strip() for item in self.allowed_form_keys if str(item).strip()]

    def __str__(self) -> str:
        return f"{self.user} - Zugriff"


class Bewohner(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class RecordStatus(models.TextChoices):
        ACTIVE = "active", "Aktiv"
        INACTIVE = "inactive", "Inaktiv"
        ARCHIVED = "archived", "Archiviert"

    public_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
        help_text="Externe, nicht sprechende Kennung fuer URLs und UI.",
    )
    resident_number = models.CharField(
        max_length=64,
        unique=True,
        help_text="Interne Bewohnernummer aus dem Fachsystem.",
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(null=True, blank=True)
    room_label = models.CharField(max_length=64, blank=True)
    org_unit = models.CharField(
        max_length=80,
        blank=True,
        db_index=True,
        help_text="Stabiler Standort-/Abteilungscode fuer rollenbasierte Zugriffsbeschraenkung.",
    )
    status = models.CharField(
        max_length=16,
        choices=RecordStatus.choices,
        default=RecordStatus.ACTIVE,
        db_index=True,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["last_name", "first_name", "resident_number"]
        indexes = [
            models.Index(fields=["public_id"]),
            models.Index(fields=["resident_number", "status"]),
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["org_unit", "status"]),
        ]
        verbose_name = "Bewohner"
        verbose_name_plural = "Bewohner"

    def __str__(self) -> str:
        return f"{self.last_name}, {self.first_name} ({self.resident_number})"


class Form(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class PublicationStatus(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        PUBLISHED = "published", "Veroeffentlicht"
        RETIRED = "retired", "Ausgemustert"

    key = models.SlugField(
        max_length=80,
        help_text="Stabile Formularfamilie, z. B. antrag-kurzzeitpflege.",
    )
    version = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Fortlaufende Versionsnummer innerhalb einer Formularfamilie.",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    org_unit = models.CharField(
        max_length=80,
        blank=True,
        db_index=True,
        help_text="Optionaler Standort-/Abteilungscode fuer scoped Rollen.",
    )
    status = models.CharField(
        max_length=16,
        choices=PublicationStatus.choices,
        default=PublicationStatus.DRAFT,
        db_index=True,
    )
    is_archivable = models.BooleanField(default=True)
    review_required = models.BooleanField(default=True)
    retention_period_days = models.PositiveIntegerField(
        default=3650,
        validators=[MinValueValidator(1), MaxValueValidator(36500)],
        help_text="Aufbewahrungsdauer fuer zugehoerige Archivunterlagen.",
    )
    schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="Abgeleitete, cachebare Struktur fuer Render- und Validierungszwecke.",
    )
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="replaced_by_versions",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["key", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["key", "version"],
                name="uniq_form_key_version",
            ),
            models.UniqueConstraint(
                fields=["key"],
                condition=Q(status="published"),
                name="uniq_published_form_per_key",
            ),
            models.CheckConstraint(
                condition=Q(status="published", published_at__isnull=False)
                | ~Q(status="published"),
                name="form_published_requires_timestamp",
            ),
        ]
        indexes = [
            models.Index(fields=["key", "status"]),
            models.Index(fields=["status", "published_at"]),
            models.Index(fields=["org_unit", "status"]),
        ]
        verbose_name = "Formular"
        verbose_name_plural = "Formulare"

    def publish(self) -> None:
        self.status = self.PublicationStatus.PUBLISHED
        self.published_at = timezone.now()
        self.full_clean()
        with transaction.atomic():
            Form.objects.filter(key=self.key, status=self.PublicationStatus.PUBLISHED).exclude(
                pk=self.pk
            ).update(
                status=self.PublicationStatus.RETIRED,
                published_at=None,
            )
            self.save()

    def build_schema(self) -> dict:
        sections: list[dict] = []
        flat_fields: list[dict] = []

        active_sections = self.sections.filter(is_active=True).order_by("position", "title")
        for section in active_sections:
            section_fields = [
                field.as_builder_dict()
                for field in section.fields.filter(is_active=True).order_by("position", "key")
            ]
            sections.append(
                {
                    "id": str(section.id),
                    "title": section.title,
                    "description": section.description,
                    "position": section.position,
                    "is_collapsible": section.is_collapsible,
                    "field_keys": [field["key"] for field in section_fields],
                    "fields": section_fields,
                }
            )
            flat_fields.extend(section_fields)

        unsectioned_fields = [
            field.as_builder_dict()
            for field in self.fields.filter(is_active=True, section__isnull=True).order_by(
                "position", "key"
            )
        ]
        flat_fields.extend(unsectioned_fields)

        return {
            "form": {
                "id": str(self.id),
                "key": self.key,
                "version": self.version,
                "title": self.title,
                "description": self.description,
                "review_required": self.review_required,
                "is_archivable": self.is_archivable,
                "retention_period_days": self.retention_period_days,
            },
            "sections": sections,
            "fields": flat_fields,
        }

    def clean(self) -> None:
        errors = {}

        if self.supersedes_id == self.id:
            errors["supersedes"] = "Ein Formular darf sich nicht selbst ersetzen."

        if self.supersedes and self.supersedes.key != self.key:
            errors["supersedes"] = (
                "Es duerfen nur Versionen derselben Formularfamilie ersetzt werden."
            )

        if self.status == self.PublicationStatus.PUBLISHED:
            if not self.pk:
                errors["status"] = (
                    "Ein Formular muss erst gespeichert werden, bevor es veroeffentlicht werden kann."
                )
            elif not self.fields.filter(is_active=True).exists():
                errors["status"] = (
                    "Ein Formular ohne aktive Felder darf nicht veroeffentlicht werden."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Direkte Statuswechsel ueber save() sollen keine Veroeffentlichung ausloesen.
        # Fuer einen sauberen Publish-Workflow immer publish() verwenden.
        if self.status == self.PublicationStatus.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        if self.status != self.PublicationStatus.PUBLISHED:
            self.published_at = None
        super().save(*args, **kwargs)

    def sync_schema(self, *, save: bool = True) -> dict:
        self.schema = self.build_schema()
        if save:
            Form.objects.filter(pk=self.pk).update(schema=self.schema, updated_at=timezone.now())
        return self.schema

    def __str__(self) -> str:
        return f"{self.title} v{self.version}"


class FormSection(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    """Logical grouping for long administrative forms."""

    form = models.ForeignKey(
        Form,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        help_text="Beschreibung oder Hilfetext fuer diesen Formularabschnitt.",
    )
    position = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Technische Reihenfolge innerhalb des Formulars.",
    )
    is_collapsible = models.BooleanField(
        default=False,
        help_text="Wenn aktiv, kann der Abschnitt in der Oberflaeche einklappbar dargestellt werden.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["form", "position", "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["form", "position"],
                name="uniq_form_section_position_per_form",
            ),
        ]
        indexes = [models.Index(fields=["form", "is_active"])]
        verbose_name = "Formularabschnitt"
        verbose_name_plural = "Formularabschnitte"

    def __str__(self) -> str:
        return f"{self.form.key} - {self.title}"


class Field(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class FieldType(models.TextChoices):
        TEXT = "text", "Text"
        TEXTAREA = "textarea", "Mehrzeilig"
        INTEGER = "integer", "Ganzzahl"
        DECIMAL = "decimal", "Dezimalzahl"
        DATE = "date", "Datum"
        DATETIME = "datetime", "Datum und Uhrzeit"
        BOOLEAN = "boolean", "Ja/Nein"
        SELECT = "select", "Auswahl"
        MULTISELECT = "multiselect", "Mehrfachauswahl"
        RADIO = "radio", "Radiogruppe"
        EMAIL = "email", "E-Mail"
        PHONE = "phone", "Telefon"
        FILE = "file", "Datei"

    class SensitivityLevel(models.TextChoices):
        NORMAL = "normal", "Normal"
        SENSITIVE = "sensitive", "Sensibel"
        SPECIAL_CATEGORY = "special_category", "Besonders sensibel"

    CHOICE_FIELD_TYPES = {
        FieldType.SELECT,
        FieldType.MULTISELECT,
        FieldType.RADIO,
    }

    form = models.ForeignKey(
        Form,
        on_delete=models.PROTECT,
        related_name="fields",
    )
    section = models.ForeignKey(
        FormSection,
        on_delete=models.SET_NULL,
        related_name="fields",
        null=True,
        blank=True,
        help_text="Optionaler Formularabschnitt. Leer bedeutet: globales Feld ohne Abschnitt.",
    )
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=255)
    help_text = models.TextField(blank=True)
    field_type = models.CharField(max_length=24, choices=FieldType.choices)
    position = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Technische Reihenfolge innerhalb des Formulars.",
    )
    required = models.BooleanField(default=False)
    sensitivity = models.CharField(
        max_length=24,
        choices=SensitivityLevel.choices,
        default=SensitivityLevel.NORMAL,
        db_index=True,
    )
    placeholder = models.CharField(max_length=255, blank=True)
    default_value = models.JSONField(null=True, blank=True)
    choices = models.JSONField(
        default=list,
        blank=True,
        help_text="Nur fuer Auswahlfelder; Liste aus stabilen value/label-Eintraegen.",
    )
    validation_rules = models.JSONField(
        default=dict,
        blank=True,
        help_text="Serverseitige Regeln wie min/max, Regex, Dateitypen oder Bereichswerte.",
    )
    ui_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Darstellungsoptionen fuer Builder und spaetere PDF-Ausgabe.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["form", "position", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["form", "key"],
                name="uniq_field_key_per_form",
            ),
            models.UniqueConstraint(
                fields=["form", "position"],
                name="uniq_field_position_per_form",
            ),
        ]
        indexes = [
            models.Index(fields=["form", "is_active"]),
            models.Index(fields=["section", "is_active"]),
            models.Index(fields=["field_type", "sensitivity"]),
        ]
        verbose_name = "Formularfeld"
        verbose_name_plural = "Formularfelder"

    def clean(self) -> None:
        errors = {}

        if self.section_id and self.form_id and self.section.form_id != self.form_id:
            errors["section"] = "Der Formularabschnitt gehoert nicht zu diesem Formular."

        if self.field_type in self.CHOICE_FIELD_TYPES:
            if not isinstance(self.choices, list) or not self.choices:
                errors["choices"] = "Auswahlfelder brauchen mindestens einen Eintrag."
            else:
                invalid_choices = [
                    choice
                    for choice in self.choices
                    if not isinstance(choice, dict)
                    or "value" not in choice
                    or "label" not in choice
                ]
                if invalid_choices:
                    errors["choices"] = (
                        "Jeder Auswahlwert muss als Objekt mit 'value' und 'label' gespeichert werden."
                    )
        elif self.choices:
            errors["choices"] = "Auswahlwerte sind nur fuer Auswahlfelder erlaubt."

        if self.default_value is not None and self.field_type == self.FieldType.BOOLEAN:
            if not isinstance(self.default_value, bool):
                errors["default_value"] = (
                    "Standardwert fuer Ja/Nein-Felder muss true oder false sein."
                )

        if not isinstance(self.validation_rules, dict):
            errors["validation_rules"] = "Validierungsregeln muessen als Objekt gespeichert werden."

        if not isinstance(self.ui_config, dict):
            errors["ui_config"] = "UI-Konfiguration muss als Objekt gespeichert werden."

        if errors:
            raise ValidationError(errors)

    def as_builder_dict(self) -> dict:
        return {
            "id": str(self.id),
            "key": self.key,
            "section_id": str(self.section_id) if self.section_id else None,
            "label": self.label,
            "help_text": self.help_text,
            "field_type": self.field_type,
            "position": self.position,
            "required": self.required,
            "sensitivity": self.sensitivity,
            "placeholder": self.placeholder,
            "default_value": self.default_value,
            "choices": self.choices,
            "validation_rules": self.validation_rules,
            "ui_config": self.ui_config,
            "is_active": self.is_active,
        }

    def __str__(self) -> str:
        return f"{self.form.key}.{self.key}"


class FormEntry(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class EntryStatus(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        IN_REVIEW = "in_review", "In Pruefung"
        APPROVED = "approved", "Freigegeben"
        REJECTED = "rejected", "Zurueckgewiesen"
        READY_TO_SEND = "ready_to_send", "Bereit zum Versand"
        ARCHIVED = "archived", "Archiviert"
        DELETED = "deleted", "Geloescht"

    public_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
        help_text="Externe, nicht sprechende Kennung fuer UI und Links.",
    )
    form = models.ForeignKey(
        Form,
        on_delete=models.PROTECT,
        related_name="entries",
    )
    bewohner = models.ForeignKey(
        Bewohner,
        on_delete=models.PROTECT,
        related_name="form_entries",
    )
    status = models.CharField(
        max_length=24,
        choices=EntryStatus.choices,
        default=EntryStatus.DRAFT,
        db_index=True,
    )
    form_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Eingefrorene Formularstruktur fuer spaetere Nachvollziehbarkeit.",
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Rohwerte nach Feld-Key, immer serverseitig validiert.",
    )
    validation_errors = models.JSONField(
        default=dict,
        blank=True,
        help_text="Zuletzt bekannte serverseitige Fehler pro Feld.",
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="locked_form_entries",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(locked_at__isnull=True, locked_by__isnull=True)
                    | Q(locked_at__isnull=False, locked_by__isnull=False)
                ),
                name="form_entry_lock_fields_match",
            ),
        ]
        indexes = [
            models.Index(fields=["public_id"]),
            models.Index(fields=["status", "updated_at"]),
            models.Index(fields=["bewohner", "status"]),
            models.Index(fields=["form", "status"]),
        ]
        verbose_name = "Formulareintrag"
        verbose_name_plural = "Formulareintraege"

    def lock(self, user) -> None:
        self.locked_by = user
        self.locked_at = timezone.now()

    def __str__(self) -> str:
        return f"{self.form} - {self.bewohner} - {self.get_status_display()}"


class FormRecipient(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class ChannelType(models.TextChoices):
        SMTP = "smtp", "SMTP"
        MICROSOFT_GRAPH = "microsoft_graph", "Microsoft Graph"

    class RecipientType(models.TextChoices):
        TO = "to", "An"
        CC = "cc", "Cc"
        BCC = "bcc", "Bcc"

    form = models.ForeignKey(
        Form,
        on_delete=models.PROTECT,
        related_name="recipients",
    )
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(max_length=254)
    recipient_type = models.CharField(
        max_length=8,
        choices=RecipientType.choices,
        default=RecipientType.TO,
    )
    channel = models.CharField(
        max_length=32,
        choices=ChannelType.choices,
        default=ChannelType.SMTP,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=True,
        help_text="Standardempfaenger fuer neue Versandvorgaenge dieses Formulars.",
    )
    subject_template = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optionaler Betreff. Platzhalter: {form}, {name}, {vorname}, {pkz}, {aktenzeichen}.",
    )
    body_template = models.TextField(
        blank=True,
        help_text="Optionaler E-Mail-Text. Platzhalter wie im Betreff nutzbar.",
    )
    dispatch_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Regulaere Versandzeit fuer dieses Formular und diesen Empfaenger.",
    )
    dispatch_frequency = models.CharField(
        max_length=16,
        blank=True,
        choices=[("manual", "Manuell"), ("daily", "Taeglich"), ("weekly", "Woechentlich")],
        help_text="Standard-Rhythmus fuer Versandplanung.",
    )
    dispatch_weekday = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(6)],
        help_text="0=Montag bis 6=Sonntag, nur fuer woechentliche Planung.",
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Kanalbezogene Zusatzparameter, z. B. Graph-Mandant oder SMTP-Profilkennung.",
    )

    class Meta:
        ordering = ["form", "recipient_type", "email"]
        constraints = [
            models.UniqueConstraint(
                fields=["form", "email", "recipient_type", "channel"],
                name="uniq_form_recipient_per_channel",
            ),
        ]
        indexes = [
            models.Index(fields=["form", "is_active"]),
            models.Index(fields=["channel", "is_active"]),
        ]
        verbose_name = "Formular-E-Mail-Ziel"
        verbose_name_plural = "Formular-E-Mail-Ziele"

    def __str__(self) -> str:
        return f"{self.form.key} -> {self.email} ({self.channel})"


class FormSchedule(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class TriggerType(models.TextChoices):
        MANUAL = "manual", "Manuell"
        IMMEDIATE = "immediate", "Sofort"
        SCHEDULED = "scheduled", "Geplant"

    class ScheduleStatus(models.TextChoices):
        ACTIVE = "active", "Aktiv"
        PAUSED = "paused", "Pausiert"
        RETIRED = "retired", "Stillgelegt"

    form = models.ForeignKey(
        Form,
        on_delete=models.PROTECT,
        related_name="schedules",
    )
    recipients = models.ManyToManyField(
        FormRecipient,
        blank=True,
        related_name="schedules",
        help_text="E-Mail-Ziele, die mit diesem Zeitplan verbunden sind.",
    )
    name = models.CharField(max_length=255)
    trigger_type = models.CharField(
        max_length=16,
        choices=TriggerType.choices,
        default=TriggerType.MANUAL,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=ScheduleStatus.choices,
        default=ScheduleStatus.ACTIVE,
        db_index=True,
    )
    timezone = models.CharField(max_length=64, default="Europe/Berlin")
    cron_expression = models.CharField(max_length=120, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Zusatzregeln fuer Trigger, Filter oder Versandfenster.",
    )

    class Meta:
        ordering = ["form", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__isnull=True) | Q(start_at__lte=models.F("end_at")),
                name="form_schedule_valid_window",
            ),
        ]
        indexes = [
            models.Index(fields=["form", "status"]),
            models.Index(fields=["next_run_at", "status"]),
        ]
        verbose_name = "Formularzeitplan"
        verbose_name_plural = "Formularzeitplaene"

    def recipient_summary(self) -> str:
        return (
            ", ".join(
                self.recipients.order_by("recipient_type", "email").values_list("email", flat=True)
            )
            or "-"
        )

    def __str__(self) -> str:
        return f"{self.form.key} - {self.name}"


class PDFDocument(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class DocumentKind(models.TextChoices):
        REVIEW = "review", "Review-PDF"
        FINAL = "final", "Finales PDF"
        ARCHIVE = "archive", "Archiv-PDF"

    class GenerationStatus(models.TextChoices):
        PENDING = "pending", "Ausstehend"
        GENERATED = "generated", "Erzeugt"
        FAILED = "failed", "Fehlgeschlagen"

    form = models.ForeignKey(
        Form,
        on_delete=models.PROTECT,
        related_name="pdf_documents",
    )
    form_entry = models.ForeignKey(
        FormEntry,
        on_delete=models.PROTECT,
        related_name="pdf_documents",
    )
    bewohner = models.ForeignKey(
        Bewohner,
        on_delete=models.PROTECT,
        related_name="pdf_documents",
    )
    document_kind = models.CharField(
        max_length=16,
        choices=DocumentKind.choices,
        default=DocumentKind.REVIEW,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=GenerationStatus.choices,
        default=GenerationStatus.PENDING,
        db_index=True,
    )
    storage_key = models.CharField(
        max_length=512,
        unique=True,
        help_text="Interner geschuetzter Speicherpfad oder Objekt-Key, niemals als oeffentlicher Link ausliefern.",
    )
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, default="application/pdf")
    file_size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    access_policy = models.JSONField(
        default=dict,
        blank=True,
        help_text="Vorbereitung fuer serverseitige Berechtigungspruefung und Download-Auditierung.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["form_entry", "document_kind"]),
            models.Index(fields=["bewohner", "status"]),
        ]
        verbose_name = "PDF-Dokument"
        verbose_name_plural = "PDF-Dokumente"

    def __str__(self) -> str:
        return f"{self.form_entry_id} - {self.document_kind}"


class OutboxItem(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", "Ausstehend"
        SENT = "sent", "Versendet"
        FAILED = "failed", "Fehlgeschlagen"

    class DeliveryChannel(models.TextChoices):
        SMTP = "smtp", "SMTP"
        MICROSOFT_GRAPH = "microsoft_graph", "Microsoft Graph"

    form = models.ForeignKey(
        Form,
        on_delete=models.PROTECT,
        related_name="outbox_items",
    )
    form_entry = models.ForeignKey(
        FormEntry,
        on_delete=models.PROTECT,
        related_name="outbox_items",
    )
    bewohner = models.ForeignKey(
        Bewohner,
        on_delete=models.PROTECT,
        related_name="outbox_items",
    )
    schedule = models.ForeignKey(
        FormSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="outbox_items",
    )
    recipient = models.ForeignKey(
        FormRecipient,
        on_delete=models.PROTECT,
        related_name="outbox_items",
    )
    pdf_document = models.ForeignKey(
        PDFDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="outbox_items",
    )
    status = models.CharField(
        max_length=16,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        db_index=True,
    )
    channel = models.CharField(
        max_length=32,
        choices=DeliveryChannel.choices,
        db_index=True,
    )
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Strukturierte Versanddaten fuer Worker, niemals als unkontrollierter Freitextspeicher.",
    )
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=100, blank=True)
    last_error_message = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    provider_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Reduzierte Provider-Rueckgaben fuer Retry, Monitoring und spaetere Audit-Events.",
    )

    class Meta:
        ordering = ["next_attempt_at", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1),
                name="outbox_item_max_attempts_gte_1",
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__gte=0),
                name="outbox_item_attempt_count_gte_0",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["channel", "status"]),
            models.Index(fields=["form_entry", "status"]),
            models.Index(fields=["bewohner", "status"]),
        ]
        verbose_name = "Ausgangskorb-Eintrag"
        verbose_name_plural = "Ausgangskorb-Eintraege"

    def clean(self) -> None:
        errors = {}

        if self.form_entry_id:
            if self.form_id and self.form_entry.form_id != self.form_id:
                errors["form_entry"] = (
                    "Der Formulareintrag gehoert nicht zum ausgewaehlten Formular."
                )
            if self.bewohner_id and self.form_entry.bewohner_id != self.bewohner_id:
                errors["bewohner"] = "Der Formulareintrag gehoert nicht zum ausgewaehlten Bewohner."

        if self.recipient_id and self.form_id and self.recipient.form_id != self.form_id:
            errors["recipient"] = "Der Empfaenger gehoert nicht zum ausgewaehlten Formular."

        if self.pdf_document_id and self.form_entry_id:
            if self.pdf_document.form_entry_id != self.form_entry_id:
                errors["pdf_document"] = (
                    "Das PDF-Dokument gehoert nicht zum ausgewaehlten Formulareintrag."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.recipient_id:
            self.channel = self.recipient.channel
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.recipient.email} - {self.get_status_display()}"


class SentFormArchive(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    form = models.ForeignKey(
        Form,
        on_delete=models.PROTECT,
        related_name="sent_archives",
    )
    form_entry = models.ForeignKey(
        FormEntry,
        on_delete=models.PROTECT,
        related_name="sent_archives",
    )
    bewohner = models.ForeignKey(
        Bewohner,
        on_delete=models.PROTECT,
        related_name="sent_archives",
    )
    outbox_item = models.ForeignKey(
        OutboxItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archive_records",
    )
    pdf_document = models.ForeignKey(
        PDFDocument,
        on_delete=models.PROTECT,
        related_name="archive_records",
    )
    archived_pdf = models.ForeignKey(
        PDFDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_sent_records",
        help_text="Optional separates Archiv-PDF, falls vom Versand-PDF abweichend.",
    )
    recipient_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Eingefrorene Empfaenger- und Kanalinformationen fuer Nachvollziehbarkeit.",
    )
    delivery_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Eingefrorene Versand- und Providerdaten fuer revisionssichere Archivierung.",
    )
    sent_at = models.DateTimeField(db_index=True)
    archived_at = models.DateTimeField(default=timezone.now, db_index=True)
    retention_until = models.DateTimeField(null=True, blank=True)
    archive_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Vorbereitung fuer Berechtigungspruefung, Download-Audit und spaetere Aufbewahrungsjobs.",
    )

    class Meta:
        ordering = ["-archived_at"]
        indexes = [
            models.Index(fields=["bewohner", "archived_at"]),
            models.Index(fields=["form_entry", "archived_at"]),
            models.Index(fields=["retention_until"]),
        ]
        verbose_name = "Versandarchiv"
        verbose_name_plural = "Versandarchiv"

    def __str__(self) -> str:
        return f"{self.form_entry_id} - {self.sent_at}"


class AuditLog(UUIDPrimaryKeyModel):
    class EventType(models.TextChoices):
        CREATED = "created", "Erstellt"
        UPDATED = "updated", "Aktualisiert"
        DELETED = "deleted", "Geloescht"
        VIEWED = "viewed", "Angesehen"
        VALIDATED = "validated", "Validiert"
        STATUS_CHANGED = "status_changed", "Status geaendert"
        PDF_RENDERED = "pdf_rendered", "PDF erzeugt"
        SENT = "sent", "Versandt"
        DOWNLOAD = "download", "Heruntergeladen"
        PERMISSION_DENIED = "permission_denied", "Zugriff verweigert"

    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="form_audit_logs",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    target_model = models.CharField(max_length=100)
    target_id = models.UUIDField()
    bewohner = models.ForeignKey(
        Bewohner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    form = models.ForeignKey(
        Form,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    form_entry = models.ForeignKey(
        FormEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    remote_addr = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    message = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Zusaetzliche, nicht frei formulierte Audit-Daten.",
    )
    previous_hash = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        help_text="SHA-256 Hash des vorherigen Audit-Eintrags fuer eine pruefbare Hash-Kette.",
    )
    entry_hash = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        db_index=True,
        help_text="SHA-256 Hash dieses Audit-Eintrags inklusive previous_hash.",
    )

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["target_model", "target_id"]),
            models.Index(fields=["event_type", "occurred_at"]),
            models.Index(fields=["bewohner", "occurred_at"]),
            models.Index(fields=["form_entry", "occurred_at"]),
        ]
        verbose_name = "Audit-Log"
        verbose_name_plural = "Audit-Logs"

    def _canonical_hash_payload(self) -> dict:
        return {
            "id": str(self.id),
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else "",
            "actor_id": str(self.actor_id or ""),
            "event_type": self.event_type,
            "target_model": self.target_model,
            "target_id": str(self.target_id),
            "bewohner_id": str(self.bewohner_id or ""),
            "form_id": str(self.form_id or ""),
            "form_entry_id": str(self.form_entry_id or ""),
            "remote_addr": self.remote_addr or "",
            "user_agent": self.user_agent or "",
            "message": self.message or "",
            "metadata": self.metadata or {},
            "previous_hash": self.previous_hash or "",
        }

    def calculate_entry_hash(self) -> str:
        payload = json.dumps(
            self._canonical_hash_payload(), sort_keys=True, default=str, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "AuditLog ist append-only und darf nicht nachtraeglich geaendert werden."
            )
        if not self.previous_hash:
            previous = AuditLog.objects.order_by("-occurred_at", "-id").only("entry_hash").first()
            self.previous_hash = previous.entry_hash if previous else ""
        self.entry_hash = self.calculate_entry_hash()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_event_type_display()} {self.target_model}:{self.target_id}"
