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
    OutboxItem,
    PDFDocument,
    SentFormArchive,
)


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


class FieldInline(admin.TabularInline):
    model = Field
    extra = 0
    fields = (
        "position",
        "key",
        "label",
        "field_type",
        "required",
        "sensitivity",
        "is_active",
    )
    ordering = ("position", "key")
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
        "status",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = ("resident_number", "first_name", "last_name", "room_label")
    readonly_fields = ("id", "public_id", "created_at", "updated_at")
    fields = (
        "id",
        "public_id",
        "resident_number",
        "first_name",
        "last_name",
        "date_of_birth",
        "room_label",
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
        "review_required",
        "is_archivable",
        "published_at",
        "updated_at",
    )
    list_filter = ("status", "review_required", "is_archivable")
    search_fields = ("title", "key", "description")
    readonly_fields = ("id", "schema", "published_at", "created_at", "updated_at")
    fields = (
        "id",
        "key",
        "version",
        "title",
        "description",
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
    inlines = (FieldInline,)
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
    list_filter = ("field_type", "required", "sensitivity", "is_active")
    search_fields = ("label", "key", "form__title", "form__key")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("form",)
    fields = (
        "id",
        "form",
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


@admin.register(FormRecipient)
class FormRecipientAdmin(PublishedFormReadOnlyMixin, UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "email",
        "name",
        "form",
        "recipient_type",
        "channel",
        "is_default",
        "is_active",
        "updated_at",
    )
    list_filter = ("channel", "recipient_type", "is_default", "is_active")
    search_fields = ("email", "name", "form__title", "form__key")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("form",)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and self._is_published_form_object(obj):
            readonly_fields.extend(
                [
                    "form",
                    "name",
                    "email",
                    "recipient_type",
                    "channel",
                    "is_default",
                    "is_active",
                    "config",
                ]
            )
        return readonly_fields


@admin.register(FormSchedule)
class FormScheduleAdmin(PublishedFormReadOnlyMixin, UserStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "form",
        "trigger_type",
        "status",
        "timezone",
        "next_run_at",
        "last_run_at",
        "is_active",
    )
    list_filter = ("trigger_type", "status", "is_active", "timezone")
    search_fields = ("name", "form__title", "form__key", "cron_expression")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("form",)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and self._is_published_form_object(obj):
            readonly_fields.extend(
                [
                    "form",
                    "name",
                    "trigger_type",
                    "status",
                    "timezone",
                    "cron_expression",
                    "start_at",
                    "end_at",
                    "next_run_at",
                    "last_run_at",
                    "is_active",
                    "config",
                ]
            )
        return readonly_fields


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
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
