from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    AuditLog,
    Bewohner,
    Field,
    Form,
    FormEntry,
    FormRecipient,
    FormSchedule,
    FormSection,
    OutboxItem,
    PDFDocument,
    SentFormArchive,
    UserAccessProfile,
)
from .schedule_services import sync_schedule_for_recipient


class UserStampedAdminMixin:
    def save_model(self, request, obj, form, change):
        if hasattr(obj, "created_by_id") and not obj.created_by_id:
            obj.created_by = request.user
        if hasattr(obj, "updated_by_id"):
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)


class PublishedFormReadOnlyMixin:
    protected_form_attr = "form"

    def _get_related_form(self, obj):
        if obj is None:
            return None
        related = getattr(obj, self.protected_form_attr, None)
        return related if isinstance(related, Form) else None

    def _is_published_form_object(self, obj):
        related_form = self._get_related_form(obj)
        return bool(related_form and related_form.status == Form.PublicationStatus.PUBLISHED)

    def has_change_permission(self, request, obj=None):
        if obj and self._is_published_form_object(obj):
            return request.method in ("GET", "HEAD", "OPTIONS")
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and self._is_published_form_object(obj):
            return False
        return super().has_delete_permission(request, obj)


class FormSectionInline(admin.TabularInline):
    model = FormSection
    extra = 0
    fields = ("position", "title", "description", "is_collapsible", "is_active")
    ordering = ("position", "title")
    show_change_link = True

    def _is_published(self, obj):
        return bool(obj and obj.pk and obj.status == Form.PublicationStatus.PUBLISHED)

    def has_add_permission(self, request, obj=None):
        if self._is_published(obj):
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._is_published(obj):
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if self._is_published(obj):
            return request.method in ("GET", "HEAD", "OPTIONS")
        return super().has_change_permission(request, obj)


class FieldInline(admin.TabularInline):
    model = Field
    extra = 0
    fields = (
        "section",
        "position",
        "key",
        "label",
        "field_type",
        "required",
        "sensitivity",
        "is_active",
    )
    ordering = ("section__position", "position", "key")
    show_change_link = True

    def _is_published(self, obj):
        return bool(obj and obj.pk and obj.status == Form.PublicationStatus.PUBLISHED)

    def has_add_permission(self, request, obj=None):
        if self._is_published(obj):
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._is_published(obj):
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if self._is_published(obj):
            return request.method in ("GET", "HEAD", "OPTIONS")
        return super().has_change_permission(request, obj)


@admin.register(Bewohner)
class BewohnerAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "resident_number",
        "last_name",
        "first_name",
        "date_of_birth",
        "room_label",
        "org_unit",
        "status",
        "updated_at",
    )
    list_filter = ("status", "org_unit")
    search_fields = ("resident_number", "first_name", "last_name", "room_label", "org_unit")
    readonly_fields = ("id", "public_id", "created_at", "updated_at")
    fields = (
        "id",
        "public_id",
        "resident_number",
        "first_name",
        "last_name",
        "date_of_birth",
        "room_label",
        "org_unit",
        "status",
        "notes",
        "created_at",
        "updated_at",
    )


@admin.register(Form)
class FormAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "title",
        "key",
        "version",
        "status",
        "org_unit",
        "review_required",
        "is_archivable",
        "published_at",
        "updated_at",
    )
    list_filter = ("status", "org_unit", "review_required", "is_archivable")
    search_fields = ("title", "key", "description", "org_unit")
    readonly_fields = ("id", "schema", "published_at", "created_at", "updated_at")
    fields = (
        "id",
        "key",
        "version",
        "title",
        "description",
        "org_unit",
        "status",
        "supersedes",
        "review_required",
        "is_archivable",
        "retention_period_days",
        "schema",
        "published_at",
        "created_at",
        "updated_at",
    )
    inlines = (FormSectionInline, FieldInline)
    actions = ("publish_selected_forms",)

    @admin.action(description="Ausgewaehlte Formulare veroeffentlichen")
    def publish_selected_forms(self, request, queryset):
        published_count = 0
        for obj in queryset:
            try:
                with transaction.atomic():
                    obj.publish()
                    obj.sync_schema()
                    published_count += 1
            except ValidationError as exc:
                self.message_user(request, f"{obj}: {exc}", level=messages.ERROR)
        if published_count:
            self.message_user(
                request,
                f"{published_count} Formular(e) wurden veroeffentlicht.",
                level=messages.SUCCESS,
            )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.status == Form.PublicationStatus.PUBLISHED:
            readonly_fields.extend(
                [
                    "key",
                    "version",
                    "title",
                    "description",
                    "org_unit",
                    "status",
                    "supersedes",
                    "review_required",
                    "is_archivable",
                    "retention_period_days",
                ]
            )
        return readonly_fields

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status == Form.PublicationStatus.PUBLISHED:
            return False
        return super().has_delete_permission(request, obj)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.sync_schema()


@admin.register(FormSection)
class FormSectionAdmin(PublishedFormReadOnlyMixin, UserStampedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "form", "position", "is_collapsible", "is_active", "updated_at")
    list_filter = ("form", "is_collapsible", "is_active")
    search_fields = ("title", "description", "form__title", "form__key")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("form",)
    fields = (
        "id",
        "form",
        "position",
        "title",
        "description",
        "is_collapsible",
        "is_active",
        "created_at",
        "updated_at",
    )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and self._is_published_form_object(obj):
            readonly_fields.extend(
                [
                    "form",
                    "position",
                    "title",
                    "description",
                    "is_collapsible",
                    "is_active",
                ]
            )
        return readonly_fields

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.form.sync_schema()

    def delete_model(self, request, obj):
        form = obj.form
        super().delete_model(request, obj)
        form.sync_schema()


@admin.register(Field)
class FieldAdmin(PublishedFormReadOnlyMixin, UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "label",
        "form",
        "position",
        "field_type",
        "required",
        "sensitivity",
        "is_active",
        "updated_at",
    )
    list_filter = ("form", "section", "field_type", "required", "sensitivity", "is_active")
    search_fields = ("label", "key", "form__title", "form__key")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("form", "section")
    fields = (
        "id",
        "form",
        "section",
        "position",
        "key",
        "label",
        "help_text",
        "field_type",
        "required",
        "sensitivity",
        "placeholder",
        "default_value",
        "choices",
        "validation_rules",
        "ui_config",
        "is_active",
        "created_at",
        "updated_at",
    )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and self._is_published_form_object(obj):
            readonly_fields.extend(
                [
                    "form",
                    "section",
                    "position",
                    "key",
                    "label",
                    "help_text",
                    "field_type",
                    "required",
                    "sensitivity",
                    "placeholder",
                    "default_value",
                    "choices",
                    "validation_rules",
                    "ui_config",
                    "is_active",
                ]
            )
        return readonly_fields

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.form.sync_schema()

    def delete_model(self, request, obj):
        form = obj.form
        super().delete_model(request, obj)
        form.sync_schema()


@admin.register(FormRecipient)
class FormRecipientAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "email",
        "name",
        "form",
        "recipient_type",
        "channel",
        "dispatch_frequency",
        "dispatch_time",
        "schedule_summary",
        "is_default",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "form",
        "channel",
        "recipient_type",
        "dispatch_frequency",
        "is_default",
        "is_active",
    )
    search_fields = ("email", "name", "form__title", "form__key", "subject_template")
    readonly_fields = ("id", "created_at", "updated_at", "schedule_summary")
    autocomplete_fields = ("form",)
    fieldsets = (
        (
            "Formular und Empfaenger",
            {
                "fields": (
                    "id",
                    "form",
                    "name",
                    "email",
                    "recipient_type",
                    "channel",
                    "is_active",
                    "is_default",
                )
            },
        ),
        (
            "Versandplanung",
            {
                "fields": (
                    "dispatch_frequency",
                    "dispatch_weekday",
                    "dispatch_time",
                    "schedule_summary",
                )
            },
        ),
        ("E-Mail Vorlage", {"fields": ("subject_template", "body_template")}),
        ("Technik", {"classes": ("collapse",), "fields": ("config", "created_at", "updated_at")}),
    )
    actions = ("sync_selected_schedules",)

    def schedule_summary(self, obj):
        if not obj or not obj.pk:
            return "Nach dem Speichern wird der passende Zeitplan verbunden."
        schedules = obj.schedules.order_by("name")
        if not schedules.exists():
            return "Kein automatischer Zeitplan verbunden."
        return ", ".join(
            f"{schedule.name} ({schedule.get_status_display()})" for schedule in schedules
        )

    schedule_summary.short_description = "Verbundene Zeitplaene"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        sync_schedule_for_recipient(obj, user=request.user)

    @admin.action(description="Zeitplaene fuer ausgewaehlte E-Mail-Ziele synchronisieren")
    def sync_selected_schedules(self, request, queryset):
        count = 0
        for recipient in queryset:
            sync_schedule_for_recipient(recipient, user=request.user)
            count += 1
        self.message_user(
            request,
            f"{count} E-Mail-Ziel(e) wurden mit Zeitplaenen synchronisiert.",
            level=messages.SUCCESS,
        )


@admin.register(FormSchedule)
class FormScheduleAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "form",
        "trigger_type",
        "status",
        "recipient_summary",
        "timezone",
        "next_run_at",
        "last_run_at",
        "is_active",
    )
    list_filter = ("form", "trigger_type", "status", "is_active", "timezone", "recipients__channel")
    search_fields = (
        "name",
        "form__title",
        "form__key",
        "cron_expression",
        "recipients__email",
        "recipients__name",
    )
    readonly_fields = ("id", "created_at", "updated_at", "recipient_summary")
    autocomplete_fields = ("form",)
    filter_horizontal = ("recipients",)
    fieldsets = (
        ("Zeitplan", {"fields": ("id", "name", "form", "trigger_type", "status", "is_active")}),
        ("E-Mail-Ziele", {"fields": ("recipients", "recipient_summary")}),
        (
            "Ausfuehrung",
            {
                "fields": (
                    "timezone",
                    "cron_expression",
                    "start_at",
                    "end_at",
                    "next_run_at",
                    "last_run_at",
                )
            },
        ),
        ("Technik", {"classes": ("collapse",), "fields": ("config", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("form").prefetch_related("recipients")

    def recipient_summary(self, obj):
        if not obj or not obj.pk:
            return "-"
        return (
            ", ".join(
                obj.recipients.order_by("recipient_type", "email").values_list("email", flat=True)
            )
            or "-"
        )

    recipient_summary.short_description = "E-Mail-Ziele"

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        schedule = form.instance
        config = dict(schedule.config or {})
        config["recipient_ids"] = [
            str(pk) for pk in schedule.recipients.values_list("pk", flat=True)
        ]
        schedule.config = config
        schedule.updated_by = request.user
        schedule.save(update_fields=["config", "updated_by", "updated_at"])


@admin.register(FormEntry)
class FormEntryAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "public_id",
        "form",
        "bewohner",
        "status",
        "locked_by",
        "updated_at",
    )
    list_filter = ("status", "form")
    search_fields = (
        "public_id",
        "form__title",
        "form__key",
        "bewohner__resident_number",
        "bewohner__last_name",
        "bewohner__first_name",
    )
    readonly_fields = (
        "id",
        "public_id",
        "form_snapshot",
        "validation_errors",
        "locked_at",
        "locked_by",
        "submitted_at",
        "archived_at",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("form", "bewohner")
    fields = (
        "id",
        "public_id",
        "form",
        "bewohner",
        "status",
        "data",
        "form_snapshot",
        "validation_errors",
        "locked_at",
        "locked_by",
        "submitted_at",
        "archived_at",
        "created_at",
        "updated_at",
    )


@admin.register(PDFDocument)
class PDFDocumentAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "original_filename",
        "document_kind",
        "status",
        "form",
        "bewohner",
        "generated_at",
        "created_at",
    )
    list_filter = ("document_kind", "status", "content_type")
    search_fields = (
        "original_filename",
        "storage_key",
        "form__title",
        "form__key",
        "bewohner__resident_number",
        "bewohner__last_name",
    )
    readonly_fields = (
        "id",
        "storage_key",
        "content_type",
        "file_size",
        "sha256",
        "page_count",
        "generated_at",
        "failed_at",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("form", "form_entry", "bewohner")
    fields = (
        "id",
        "form",
        "form_entry",
        "bewohner",
        "document_kind",
        "status",
        "storage_key",
        "original_filename",
        "content_type",
        "file_size",
        "sha256",
        "page_count",
        "generated_at",
        "failed_at",
        "failure_reason",
        "access_policy",
        "created_at",
        "updated_at",
    )


@admin.register(OutboxItem)
class OutboxItemAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "recipient",
        "form",
        "channel",
        "status",
        "attempt_count",
        "max_attempts",
        "next_attempt_at",
        "sent_at",
    )
    list_filter = ("channel", "status")
    search_fields = (
        "recipient__email",
        "subject",
        "provider_message_id",
        "form__title",
        "form__key",
        "bewohner__resident_number",
    )
    readonly_fields = (
        "id",
        "channel",
        "attempt_count",
        "last_attempt_at",
        "sent_at",
        "failed_at",
        "provider_message_id",
        "provider_payload",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "form",
        "form_entry",
        "bewohner",
        "schedule",
        "recipient",
        "pdf_document",
    )
    fields = (
        "id",
        "form",
        "form_entry",
        "bewohner",
        "schedule",
        "recipient",
        "pdf_document",
        "status",
        "channel",
        "subject",
        "body",
        "payload",
        "attempt_count",
        "max_attempts",
        "last_attempt_at",
        "next_attempt_at",
        "sent_at",
        "failed_at",
        "last_error_code",
        "last_error_message",
        "provider_message_id",
        "provider_payload",
        "created_at",
        "updated_at",
    )


@admin.register(SentFormArchive)
class SentFormArchiveAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "form_entry",
        "bewohner",
        "sent_at",
        "archived_at",
        "retention_until",
    )
    list_filter = ("sent_at", "archived_at")
    search_fields = (
        "form__title",
        "form__key",
        "bewohner__resident_number",
        "bewohner__last_name",
        "pdf_document__original_filename",
    )
    readonly_fields = ("id", "sent_at", "archived_at", "created_at", "updated_at")
    autocomplete_fields = (
        "form",
        "form_entry",
        "bewohner",
        "outbox_item",
        "pdf_document",
        "archived_pdf",
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "event_type",
        "target_model",
        "target_id",
        "actor",
        "bewohner",
        "entry_hash",
    )
    list_filter = ("event_type", "target_model")
    search_fields = ("target_model", "target_id", "message", "actor__username")
    readonly_fields = (
        "id",
        "occurred_at",
        "actor",
        "event_type",
        "target_model",
        "target_id",
        "bewohner",
        "form",
        "form_entry",
        "remote_addr",
        "user_agent",
        "message",
        "metadata",
        "previous_hash",
        "entry_hash",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserAccessProfile)
class UserAccessProfileAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "user",
        "is_active",
        "scope_mode",
        "can_dashboard",
        "can_forms",
        "can_create",
        "can_send",
        "can_archive",
        "can_settings",
        "can_manage_settings",
    )
    list_filter = (
        "is_active",
        "scope_mode",
        "can_settings",
        "can_manage_settings",
        "can_send",
        "can_archive",
    )
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email")
    autocomplete_fields = ("user",)
    readonly_fields = ("id", "created_at", "updated_at")
    fields = (
        "id",
        "user",
        "is_active",
        "scope_mode",
        "org_units",
        "allowed_form_keys",
        ("can_dashboard", "can_forms"),
        ("can_create", "can_send", "can_archive"),
        ("can_settings", "can_manage_settings"),
        "created_at",
        "updated_at",
    )
