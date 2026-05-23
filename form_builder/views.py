import logging
from types import SimpleNamespace
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .action_item_models import ActionItemRule
from .conditional_models import ConditionalRule
from .forms import (
    ConfirmDeleteForm,
    FieldBuilderForm,
    FormBuilderMetadataForm,
    FormRecipientSettingsForm,
    FormSectionBuilderForm,
    UserAccessProfileForm,
)
from .mail_services import process_outbox_queue
from .models import (
    AuditLog,
    Field,
    Form,
    FormEntry,
    FormRecipient,
    FormSchedule,
    FormSection,
    PDFDocument,
    UserAccessProfile,
)
from .navigation import get_navigation_items
from .pdf_services import (
    generate_entry_pdf_document,
    get_latest_generated_pdf_document,
    get_pdf_private_path,
    render_entry_pdf_bytes,
    render_entry_pdf_html,
)
from .permissions import can_create_entries
from .permissions import can_edit_entry as can_edit_entry_object
from .permissions import can_manage_settings, can_review_entries
from .permissions import can_review_entry as can_review_entry_object
from .permissions import can_send_entries
from .permissions import can_send_entry as can_send_entry_object
from .permissions import (
    can_view_archive,
    can_view_dashboard,
    can_view_entry,
    can_view_forms,
    can_view_pdf_document,
    can_view_settings,
)
from .repeatable_models import RepeatableGroup, RepeatableGroupColumn
from .schedule_forms import FormScheduleForm
from .schedule_services import run_due_schedules
from .selectors import (
    get_archive_queryset,
    get_available_forms_queryset,
    get_dashboard_counts,
    get_entries_in_review_queryset,
    get_frequent_forms,
    get_outbox_pending_queryset,
    get_pending_dispatch_groups,
    get_recent_activity,
    get_sent_outbox_queryset,
    get_user_drafts_queryset,
)
from .services import (
    approve_entry_for_sending,
    build_entry_form,
    build_entry_form_for_entry,
    create_form_entry_from_validated,
    queue_entry_for_delivery,
    reject_entry_for_correction,
    save_draft_from_validated,
    submit_draft_for_review,
    validate_draft,
)

logger = logging.getLogger(__name__)

EDITABLE_ENTRY_STATUSES = {
    FormEntry.EntryStatus.DRAFT,
    FormEntry.EntryStatus.REJECTED,
}


def require_permission(condition: bool):
    if not condition:
        raise PermissionDenied


def require_entry_permission(user, form_entry: FormEntry, *, action: str = "view") -> None:
    if action == "edit":
        allowed = can_edit_entry_object(user, form_entry)
    elif action == "review":
        allowed = can_review_entry_object(user, form_entry)
    elif action == "send":
        allowed = can_send_entry_object(user, form_entry)
    else:
        allowed = can_view_entry(user, form_entry)
    if not allowed:
        AuditLog.objects.create(
            actor=user if getattr(user, "is_authenticated", False) else None,
            event_type=AuditLog.EventType.PERMISSION_DENIED,
            target_model="FormEntry",
            target_id=form_entry.pk,
            bewohner=form_entry.bewohner,
            form=form_entry.form,
            form_entry=form_entry,
            message="Objektzugriff auf Formulareintrag wurde verweigert.",
            metadata={"action": action},
        )
        raise PermissionDenied


def safe_pdf_error_response() -> HttpResponse:
    return HttpResponse(
        "PDF konnte nicht erzeugt werden. Bitte Server-Log pruefen oder Support kontaktieren.",
        status=500,
        content_type="text/plain; charset=utf-8",
    )


def build_app_context(request, *, title: str, current_url_name: str, **extra):
    return {
        "page_title": title,
        "navigation_items": get_navigation_items(request.user, current_url_name=current_url_name),
        "current_url_name": current_url_name,
        **extra,
    }


def build_payload_from_schema(schema: dict, post_data) -> dict:
    """Build a best-effort PDF payload from current editor fields without saving."""
    payload = {}
    for field_definition in schema.get("fields", []):
        key = field_definition.get("key")
        field_type = field_definition.get("field_type")
        if not key:
            continue
        if field_type == "multiselect":
            payload[key] = (
                post_data.getlist(key) if hasattr(post_data, "getlist") else post_data.get(key, [])
            )
        elif field_type == "boolean":
            payload[key] = key in post_data and post_data.get(key) not in (
                "",
                "false",
                "False",
                "0",
            )
        else:
            payload[key] = post_data.get(key, "")
    return payload


def build_unsaved_preview_payload(form_entry: FormEntry, post_data) -> dict:
    return build_payload_from_schema(form_entry.form_snapshot or {}, post_data)


def make_preview_entry(form_definition: Form, payload: dict):
    """Duck-typed FormEntry for PDF rendering before the first draft is saved."""
    bewohner = SimpleNamespace(
        first_name=payload.get("vorname", ""),
        last_name=payload.get("name") or payload.get("nachname") or "Formularvorschau",
        date_of_birth=payload.get("geb_am") or payload.get("geburtsdatum") or None,
        __str__=lambda self: "Formularvorschau",
    )

    def _status_display():
        return "Vorschau"

    return SimpleNamespace(
        pk=None,
        id=None,
        public_id=uuid4(),
        form=form_definition,
        bewohner=bewohner,
        status="preview",
        data=payload,
        form_snapshot=form_definition.schema or form_definition.build_schema(),
        get_status_display=_status_display,
    )


def render_entry_response(request, template_name, context, status=200):
    return render(request, template_name, context, status=status)


def get_entry_detail_rows(form_entry: FormEntry) -> list[dict]:
    detail_rows = []
    for field_definition in form_entry.form_snapshot.get("fields", []):
        value = form_entry.data.get(field_definition["key"], "-")
        if (field_definition.get("ui_config") or {}).get("widget") == "signature":
            value = "Unterschrieben" if value not in (None, "") else "-"
        elif isinstance(value, list):
            value = ", ".join(str(item) for item in value) or "-"
        if value in (None, ""):
            value = "-"
        detail_rows.append(
            {
                "label": field_definition["label"],
                "value": value,
                "field_type": field_definition.get("field_type", "text"),
                "sensitivity": field_definition.get("sensitivity", "normal"),
            }
        )
    return detail_rows


@login_required(login_url="login")
def dashboard_view(request):
    require_permission(can_view_dashboard(request.user))
    context = build_app_context(
        request,
        title="Dashboard",
        current_url_name="form_builder:dashboard",
        dashboard_counts=get_dashboard_counts(request.user),
        frequent_forms=get_frequent_forms(user=request.user),
        recent_activity=get_recent_activity(user=request.user),
        dispatch_groups=get_pending_dispatch_groups(request.user),
    )
    return render(request, "form_builder/dashboard.html", context)


@login_required(login_url="login")
def form_list_view(request):
    require_permission(can_view_forms(request.user))
    context = build_app_context(
        request,
        title="Formulare",
        current_url_name="form_builder:form_list",
        forms=get_available_forms_queryset(request.user),
        can_create_entries=can_create_entries(request.user),
    )
    return render(request, "form_builder/form_list.html", context)


@login_required(login_url="login")
def draft_list_view(request):
    require_permission(can_view_forms(request.user))
    context = build_app_context(
        request,
        title="Entwuerfe",
        current_url_name="form_builder:draft_list",
        entries=get_user_drafts_queryset(request.user),
    )
    return render(request, "form_builder/draft_list.html", context)


@login_required(login_url="login")
def review_list_view(request):
    require_permission(can_view_forms(request.user))
    context = build_app_context(
        request,
        title="Review",
        current_url_name="form_builder:review_list",
        entries=get_entries_in_review_queryset(request.user),
    )
    return render(request, "form_builder/review_list.html", context)


@login_required(login_url="login")
def outbox_list_view(request):
    require_permission(can_view_forms(request.user))
    context = build_app_context(
        request,
        title="Ausgangskorb",
        current_url_name="form_builder:outbox_list",
        items=get_outbox_pending_queryset(request.user),
        dispatch_groups=get_pending_dispatch_groups(request.user),
        can_process_outbox=can_send_entries(request.user),
    )
    return render(request, "form_builder/outbox_list.html", context)


@login_required(login_url="login")
def process_outbox_view(request):
    require_permission(can_send_entries(request.user))
    if request.method != "POST":
        return redirect("form_builder:outbox_list")
    result = process_outbox_queue(limit=20)
    if result.failed:
        messages.warning(request, result.summary_de())
    elif result.sent:
        messages.success(request, result.summary_de())
    else:
        messages.info(request, "Keine faelligen Versandvorgaenge gefunden.")
    return redirect("form_builder:outbox_list")


@login_required(login_url="login")
def sent_list_view(request):
    require_permission(can_view_forms(request.user))
    context = build_app_context(
        request,
        title="Versandt",
        current_url_name="form_builder:sent_list",
        items=get_sent_outbox_queryset(request.user),
    )
    return render(request, "form_builder/sent_list.html", context)


@login_required(login_url="login")
def archive_list_view(request):
    require_permission(can_view_archive(request.user))
    context = build_app_context(
        request,
        title="Archiv",
        current_url_name="form_builder:archive_list",
        items=get_archive_queryset(request.user),
    )
    return render(request, "form_builder/archive_list.html", context)


@login_required(login_url="login")
def profile_view(request):
    context = build_app_context(
        request,
        title="Profil",
        current_url_name="form_builder:profile",
        audit_logs=(
            request.user.form_audit_logs.select_related("form", "bewohner", "form_entry").order_by(
                "-occurred_at"
            )[:10]
        ),
    )
    return render(request, "form_builder/profile/profile_detail.html", context)


@login_required(login_url="login")
def settings_index_view(request):
    require_permission(can_view_settings(request.user))
    context = build_app_context(
        request,
        title="Einstellungen",
        current_url_name="form_builder:settings_index",
        can_manage_settings=can_manage_settings(request.user),
        active_recipients=FormRecipient.objects.filter(is_active=True).count(),
        recipients=FormRecipient.objects.select_related("form").order_by(
            "form__title", "recipient_type", "email"
        )[:8],
        staff_profiles=UserAccessProfile.objects.select_related("user").order_by("user__username")[
            :8
        ],
        active_schedules=FormSchedule.objects.filter(is_active=True).count(),
        pending_outbox=get_outbox_pending_queryset(request.user).count(),
        available_forms=get_available_forms_queryset(request.user).count(),
    )
    return render(request, "form_builder/settings/index.html", context)


@login_required(login_url="login")
def email_target_list_view(request):
    require_permission(can_view_settings(request.user))
    recipients = FormRecipient.objects.select_related("form").order_by(
        "form__title", "recipient_type", "email"
    )
    context = build_app_context(
        request,
        title="E-Mail-Ziele",
        current_url_name="form_builder:email_target_list",
        recipients=recipients,
        can_manage_settings=can_manage_settings(request.user),
    )
    return render(request, "form_builder/settings/email_target_list.html", context)


@login_required(login_url="login")
def email_target_create_view(request):
    require_permission(can_manage_settings(request.user))
    if request.method == "POST":
        form = FormRecipientSettingsForm(request.POST)
        if form.is_valid():
            recipient = form.save(commit=False)
            recipient.created_by = request.user
            recipient.updated_by = request.user
            recipient.save()
            messages.success(request, "E-Mail-Ziel wurde gespeichert.")
            return redirect("form_builder:email_target_list")
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        form = FormRecipientSettingsForm()
    context = build_app_context(
        request,
        title="E-Mail-Ziel",
        current_url_name="form_builder:email_target_list",
        recipient_form=form,
        mode="create",
    )
    return render(request, "form_builder/settings/email_target_form.html", context)


@login_required(login_url="login")
def email_target_edit_view(request, recipient_id):
    require_permission(can_manage_settings(request.user))
    recipient = get_object_or_404(FormRecipient.objects.select_related("form"), pk=recipient_id)
    if request.method == "POST":
        form = FormRecipientSettingsForm(request.POST, instance=recipient)
        if form.is_valid():
            recipient = form.save(commit=False)
            recipient.updated_by = request.user
            recipient.save()
            messages.success(request, "E-Mail-Ziel wurde aktualisiert.")
            return redirect("form_builder:email_target_list")
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        form = FormRecipientSettingsForm(instance=recipient)
    context = build_app_context(
        request,
        title="E-Mail-Ziel",
        current_url_name="form_builder:email_target_list",
        recipient=recipient,
        recipient_form=form,
        mode="edit",
    )
    return render(request, "form_builder/settings/email_target_form.html", context)


@login_required(login_url="login")
def staff_access_list_view(request):
    require_permission(can_view_settings(request.user))
    profiles = UserAccessProfile.objects.select_related("user").order_by("user__username")
    context = build_app_context(
        request,
        title="Mitarbeiter-Zugriffe",
        current_url_name="form_builder:staff_access_list",
        profiles=profiles,
        can_manage_settings=can_manage_settings(request.user),
    )
    return render(request, "form_builder/settings/staff_access_list.html", context)


@login_required(login_url="login")
def staff_access_create_view(request):
    require_permission(can_manage_settings(request.user))
    if request.method == "POST":
        form = UserAccessProfileForm(request.POST)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.created_by = request.user
            profile.updated_by = request.user
            profile.save()
            messages.success(request, "Zugriff wurde gespeichert.")
            return redirect("form_builder:staff_access_list")
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        form = UserAccessProfileForm()
    context = build_app_context(
        request,
        title="Mitarbeiter-Zugriff",
        current_url_name="form_builder:staff_access_list",
        access_form=form,
        mode="create",
    )
    return render(request, "form_builder/settings/staff_access_form.html", context)


@login_required(login_url="login")
def staff_access_edit_view(request, profile_id):
    require_permission(can_manage_settings(request.user))
    profile = get_object_or_404(UserAccessProfile.objects.select_related("user"), pk=profile_id)
    if request.method == "POST":
        form = UserAccessProfileForm(request.POST, instance=profile)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.updated_by = request.user
            profile.save()
            messages.success(request, "Zugriff wurde aktualisiert.")
            return redirect("form_builder:staff_access_list")
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        form = UserAccessProfileForm(instance=profile)
    context = build_app_context(
        request,
        title="Mitarbeiter-Zugriff",
        current_url_name="form_builder:staff_access_list",
        profile=profile,
        access_form=form,
        mode="edit",
    )
    return render(request, "form_builder/settings/staff_access_form.html", context)


@login_required(login_url="login")
def schedule_list_view(request):
    require_permission(can_view_settings(request.user))
    schedules = (
        FormSchedule.objects.select_related("form")
        .prefetch_related("recipients")
        .order_by("form__title", "name")
    )
    context = build_app_context(
        request,
        title="Zeitplaene",
        current_url_name="form_builder:schedule_list",
        schedules=schedules,
        can_manage_settings=can_manage_settings(request.user),
    )
    return render(request, "form_builder/schedules/schedule_list.html", context)


@login_required(login_url="login")
def schedule_create_view(request):
    require_permission(can_manage_settings(request.user))
    if request.method == "POST":
        form = FormScheduleForm(request.POST)
        if form.is_valid():
            schedule = form.save(commit=False)
            schedule.created_by = request.user
            schedule.updated_by = request.user
            schedule.save()
            form.save_recipients(schedule)
            messages.success(
                request, "Zeitplan wurde angelegt und mit den E-Mail-Zielen verbunden."
            )
            return redirect("form_builder:schedule_list")
        messages.error(request, "Zeitplan konnte nicht gespeichert werden. Bitte Eingaben pruefen.")
    else:
        form = FormScheduleForm()
    context = build_app_context(
        request,
        title="Zeitplan anlegen",
        current_url_name="form_builder:schedule_list",
        schedule_form=form,
        mode="create",
    )
    return render(request, "form_builder/schedules/schedule_form.html", context)


@login_required(login_url="login")
def schedule_edit_view(request, schedule_id):
    require_permission(can_manage_settings(request.user))
    schedule = get_object_or_404(FormSchedule.objects.select_related("form"), pk=schedule_id)
    if request.method == "POST":
        form = FormScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            schedule = form.save(commit=False)
            schedule.updated_by = request.user
            schedule.save()
            form.save_recipients(schedule)
            messages.success(
                request, "Zeitplan wurde aktualisiert und mit den E-Mail-Zielen synchronisiert."
            )
            return redirect("form_builder:schedule_list")
        messages.error(
            request, "Zeitplan konnte nicht aktualisiert werden. Bitte Eingaben pruefen."
        )
    else:
        form = FormScheduleForm(instance=schedule)
    context = build_app_context(
        request,
        title="Zeitplan bearbeiten",
        current_url_name="form_builder:schedule_list",
        schedule=schedule,
        schedule_form=form,
        mode="edit",
    )
    return render(request, "form_builder/schedules/schedule_form.html", context)


@login_required(login_url="login")
def schedule_toggle_view(request, schedule_id):
    require_permission(can_manage_settings(request.user))
    schedule = get_object_or_404(FormSchedule, pk=schedule_id)
    if request.method != "POST":
        return redirect("form_builder:schedule_list")
    if schedule.status == FormSchedule.ScheduleStatus.ACTIVE and schedule.is_active:
        schedule.status = FormSchedule.ScheduleStatus.PAUSED
        schedule.is_active = False
        message = "Zeitplan wurde pausiert."
    else:
        schedule.status = FormSchedule.ScheduleStatus.ACTIVE
        schedule.is_active = True
        message = "Zeitplan wurde aktiviert."
    schedule.updated_by = request.user
    schedule.save(update_fields=["status", "is_active", "updated_by", "updated_at"])
    messages.success(request, message)
    return redirect("form_builder:schedule_list")


@login_required(login_url="login")
def process_schedules_view(request):
    require_permission(can_manage_settings(request.user))
    if request.method != "POST":
        return redirect("form_builder:schedule_list")
    result = run_due_schedules(limit_per_schedule=100)
    send_result = process_outbox_queue(limit=100)
    summary = result.summary_de() + " " + send_result.summary_de()
    if result.errors or send_result.failed:
        messages.warning(request, summary + " Bitte Details im Server-Log pruefen.")
    elif result.queued or send_result.sent:
        messages.success(request, summary)
    else:
        messages.info(request, summary)
    return redirect("form_builder:schedule_list")


def send_form_entry_immediately(*, form_entry: FormEntry, user):
    """Generate a final PDF, queue all active recipients and process the queue now."""
    if form_entry.status != FormEntry.EntryStatus.APPROVED:
        raise ValidationError("Nur freigegebene Vorgaenge duerfen verschickt werden.")
    created_items = queue_entry_for_delivery(form_entry=form_entry, user=user)
    send_result = process_outbox_queue(limit=max(len(created_items), 1))
    return created_items, send_result


def add_send_result_message(request, send_result) -> None:
    if send_result.failed:
        messages.warning(request, send_result.summary_de())
    elif send_result.sent:
        messages.success(request, "Versand wurde verarbeitet. " + send_result.summary_de())
    else:
        messages.info(
            request, "Vorgang wurde fuer den Versand vorbereitet. " + send_result.summary_de()
        )


@login_required(login_url="login")
def entry_create_view(request, form_id):
    require_permission(can_create_entries(request.user))
    form_definition = get_object_or_404(
        Form,
        pk=form_id,
        status=Form.PublicationStatus.PUBLISHED,
    )
    if request.method == "POST":
        entry_form = build_entry_form(form_definition, data=request.POST, include_bewohner=False)
        if entry_form.is_valid():
            form_entry = create_form_entry_from_validated(
                form_definition=form_definition,
                cleaned_data=entry_form.cleaned_data,
                user=request.user,
            )
            messages.success(request, "Entwurf wurde angelegt.")
            return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
        messages.error(request, "Bitte pruefe die Eingaben.")
    else:
        entry_form = build_entry_form(form_definition, include_bewohner=False)

    return render_entry_response(
        request,
        "form_builder/entry_create.html",
        build_app_context(
            request,
            title="Neuen Entwurf anlegen",
            current_url_name="form_builder:form_list",
            form_definition=form_definition,
            entry_form=entry_form,
        ),
    )


@login_required(login_url="login")
def entry_detail_view(request, entry_id):
    require_permission(can_view_forms(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by"),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="view")
    return render(
        request,
        "form_builder/entry_detail.html",
        build_app_context(
            request,
            title="Formulareintrag",
            current_url_name="form_builder:draft_list",
            form_entry=form_entry,
            detail_rows=get_entry_detail_rows(form_entry),
            can_edit_entry=can_edit_entry_object(request.user, form_entry)
            and form_entry.status in EDITABLE_ENTRY_STATUSES,
            can_review_entry=can_review_entry_object(request.user, form_entry)
            and form_entry.status == FormEntry.EntryStatus.IN_REVIEW,
            can_queue_entry=can_send_entry_object(request.user, form_entry)
            and form_entry.status == FormEntry.EntryStatus.APPROVED,
            can_send_entry=can_send_entry_object(request.user, form_entry)
            and form_entry.status == FormEntry.EntryStatus.APPROVED,
            latest_pdf_document=get_latest_generated_pdf_document(form_entry),
        ),
    )


@login_required(login_url="login")
def entry_edit_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="edit")
    if form_entry.status not in EDITABLE_ENTRY_STATUSES:
        messages.info(request, "Dieser Eintrag ist nicht mehr im Entwurfsmodus bearbeitbar.")
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    entry_form = build_entry_form_for_entry(form_entry)
    return render(
        request,
        "form_builder/entry_edit.html",
        build_app_context(
            request,
            title="Entwurf bearbeiten",
            current_url_name="form_builder:draft_list",
            form_entry=form_entry,
            entry_form=entry_form,
            pdf_inline_url=None,
        ),
    )


@login_required(login_url="login")
def entry_save_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="edit")
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
    if form_entry.status not in EDITABLE_ENTRY_STATUSES:
        messages.error(request, "Dieser Eintrag kann nicht mehr als Entwurf gespeichert werden.")
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)

    entry_form = build_entry_form_for_entry(form_entry, data=request.POST)
    if entry_form.is_valid():
        save_draft_from_validated(
            form_entry=form_entry,
            cleaned_data=entry_form.cleaned_data,
            user=request.user,
        )
        messages.success(request, "Entwurf wurde gespeichert.")
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)

    messages.error(request, "Entwurf konnte nicht gespeichert werden. Bitte Eingaben pruefen.")
    return render_entry_response(
        request,
        "form_builder/entry_edit.html",
        build_app_context(
            request,
            title="Entwurf bearbeiten",
            current_url_name="form_builder:draft_list",
            form_entry=form_entry,
            entry_form=entry_form,
        ),
        status=400,
    )


@login_required(login_url="login")
def entry_send_now_view(request, entry_id):
    require_permission(can_send_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="send")
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
    if form_entry.status in (FormEntry.EntryStatus.ARCHIVED, FormEntry.EntryStatus.DELETED):
        messages.error(request, "Dieser Eintrag ist bereits abgeschlossen.")
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    if form_entry.status != FormEntry.EntryStatus.APPROVED:
        messages.error(request, "Nur freigegebene Vorgaenge duerfen verschickt werden.")
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)

    if request.POST.get("send_saved") == "1":
        try:
            _, send_result = send_form_entry_immediately(form_entry=form_entry, user=request.user)
        except ValidationError as exc:
            messages.error(request, exc.message)
            return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
        add_send_result_message(request, send_result)
        return redirect("form_builder:sent_list")

    try:
        _, send_result = send_form_entry_immediately(form_entry=form_entry, user=request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)

    add_send_result_message(request, send_result)
    return redirect("form_builder:sent_list")


@login_required(login_url="login")
def entry_validate_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="edit")
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
    if form_entry.status not in EDITABLE_ENTRY_STATUSES:
        messages.error(request, "Dieser Eintrag kann nicht mehr als Entwurf validiert werden.")
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)

    entry_form = build_entry_form_for_entry(form_entry, data=request.POST)
    if entry_form.is_valid():
        validate_draft(
            form_entry=form_entry,
            cleaned_data=entry_form.cleaned_data,
            user=request.user,
        )
        messages.success(request, "Entwurf ist valide.")
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)

    messages.error(request, "Validierung fehlgeschlagen. Bitte Eingaben pruefen.")
    return render_entry_response(
        request,
        "form_builder/entry_edit.html",
        build_app_context(
            request,
            title="Entwurf bearbeiten",
            current_url_name="form_builder:draft_list",
            form_entry=form_entry,
            entry_form=entry_form,
        ),
        status=400,
    )


@login_required(login_url="login")
def entry_review_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="edit")
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
    if form_entry.status not in EDITABLE_ENTRY_STATUSES:
        messages.error(request, "Dieser Eintrag kann nicht erneut in Review gesetzt werden.")
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)

    entry_form = build_entry_form_for_entry(form_entry, data=request.POST)
    if entry_form.is_valid():
        try:
            submit_draft_for_review(
                form_entry=form_entry,
                cleaned_data=entry_form.cleaned_data,
                user=request.user,
            )
        except ValidationError as exc:
            entry_form.add_error(None, exc.message)
        else:
            messages.success(request, "Entwurf wurde in die Pruefung gegeben.")
            return redirect("form_builder:entry_detail", entry_id=form_entry.pk)

    messages.error(request, "Review-Status konnte nicht gesetzt werden.")
    return render_entry_response(
        request,
        "form_builder/entry_edit.html",
        build_app_context(
            request,
            title="Entwurf bearbeiten",
            current_url_name="form_builder:draft_list",
            form_entry=form_entry,
            entry_form=entry_form,
        ),
        status=400,
    )


@login_required(login_url="login")
def entry_approve_view(request, entry_id):
    require_permission(can_review_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="review")
    if request.method != "POST":
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    try:
        approve_entry_for_sending(form_entry=form_entry, user=request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, "Formulareintrag wurde freigegeben.")
    return redirect("form_builder:entry_detail", entry_id=form_entry.pk)


@login_required(login_url="login")
def entry_reject_view(request, entry_id):
    require_permission(can_review_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="review")
    if request.method != "POST":
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    reason = request.POST.get("reason", "").strip()
    try:
        reject_entry_for_correction(form_entry=form_entry, user=request.user, reason=reason)
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.warning(request, "Formulareintrag wurde zur Nachbearbeitung zurueckgewiesen.")
    return redirect("form_builder:entry_detail", entry_id=form_entry.pk)


@login_required(login_url="login")
def entry_queue_view(request, entry_id):
    require_permission(can_send_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="send")
    if request.method != "POST":
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    try:
        created_items = queue_entry_for_delivery(form_entry=form_entry, user=request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(
            request, f"{len(created_items)} Versandvorgang wurde in den Ausgangskorb gestellt."
        )
        return redirect("form_builder:outbox_list")
    return redirect("form_builder:entry_detail", entry_id=form_entry.pk)


@login_required(login_url="login")
def form_blank_pdf_view(request, form_id):
    require_permission(can_view_forms(request.user))
    form_definition = get_object_or_404(Form, pk=form_id, status=Form.PublicationStatus.PUBLISHED)
    preview_entry = make_preview_entry(form_definition, {})
    try:
        pdf_bytes = render_entry_pdf_bytes(
            form_entry=preview_entry, generated_by=request.user, data_override={}
        )
    except Exception:
        logger.exception("Blank PDF generation failed for form_id=%s", form_id)
        return safe_pdf_error_response()
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{form_definition.key}_leer.pdf"'
    return response


@login_required(login_url="login")
def entry_pdf_new_live_preview_view(request, form_id):
    require_permission(can_create_entries(request.user))
    form_definition = get_object_or_404(Form, pk=form_id, status=Form.PublicationStatus.PUBLISHED)
    schema = form_definition.schema or form_definition.build_schema()
    payload = build_payload_from_schema(schema, request.POST) if request.method == "POST" else {}
    preview_entry = make_preview_entry(form_definition, payload)
    try:
        pdf_bytes = render_entry_pdf_bytes(
            form_entry=preview_entry, generated_by=request.user, data_override=payload
        )
    except Exception:
        logger.exception("PDF preview generation failed")
        return safe_pdf_error_response()
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{form_definition.key}_live_preview.pdf"'
    return response


@login_required(login_url="login")
def entry_pdf_preview_view(request, entry_id):
    require_permission(can_view_forms(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by"),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="view")
    if request.GET.get("inline") == "1":
        try:
            pdf_bytes = render_entry_pdf_bytes(form_entry=form_entry, generated_by=request.user)
        except Exception:
            logger.exception("Inline PDF preview generation failed for entry_id=%s", entry_id)
            return safe_pdf_error_response()
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="{form_entry.form.key}_{form_entry.public_id}_preview.pdf"'
        )
        return response
    return render(
        request,
        "form_builder/pdf_preview.html",
        build_app_context(
            request,
            title="PDF-Vorschau",
            current_url_name="form_builder:draft_list",
            form_entry=form_entry,
            pdf_html=render_entry_pdf_html(form_entry=form_entry, generated_by=request.user),
            latest_pdf_document=get_latest_generated_pdf_document(form_entry),
        ),
    )


@login_required(login_url="login")
def entry_pdf_live_preview_view(request, entry_id):
    require_permission(can_view_forms(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by"),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="view")
    data_override = (
        build_unsaved_preview_payload(form_entry, request.POST)
        if request.method == "POST"
        else None
    )
    try:
        pdf_bytes = render_entry_pdf_bytes(
            form_entry=form_entry, generated_by=request.user, data_override=data_override
        )
    except Exception:
        logger.exception("PDF preview generation failed")
        return safe_pdf_error_response()
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="{form_entry.form.key}_{form_entry.public_id}_live.pdf"'
    )
    return response


@login_required(login_url="login")
def entry_pdf_generate_view(request, entry_id):
    require_permission(can_review_entries(request.user) or can_send_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(
        request.user, form_entry, action="review" if can_review_entries(request.user) else "send"
    )
    if request.method != "POST":
        return redirect("form_builder:entry_pdf_preview", entry_id=form_entry.pk)
    try:
        pdf_document = generate_entry_pdf_document(form_entry=form_entry, user=request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("form_builder:entry_pdf_preview", entry_id=form_entry.pk)
    messages.success(request, "PDF wurde privat erzeugt und gespeichert.")
    return redirect("form_builder:pdf_download", pdf_id=pdf_document.pk)


@login_required(login_url="login")
def pdf_download_view(request, pdf_id):
    require_permission(can_view_forms(request.user))
    pdf_document = get_object_or_404(
        PDFDocument.objects.select_related("form", "form_entry", "bewohner"),
        pk=pdf_id,
        status=PDFDocument.GenerationStatus.GENERATED,
    )
    require_permission(can_view_pdf_document(request.user, pdf_document))
    path = get_pdf_private_path(pdf_document)
    if not path.exists():
        raise Http404("PDF-Datei wurde nicht gefunden.")
    AuditLog.objects.create(
        actor=request.user,
        event_type=AuditLog.EventType.DOWNLOAD,
        target_model="PDFDocument",
        target_id=pdf_document.pk,
        bewohner=pdf_document.bewohner,
        form=pdf_document.form,
        form_entry=pdf_document.form_entry,
        message="PDF wurde heruntergeladen.",
        metadata={"pdf_document_id": str(pdf_document.pk), "sha256": pdf_document.sha256},
    )
    return FileResponse(
        path.open("rb"),
        as_attachment=False,
        filename=pdf_document.original_filename,
        content_type=pdf_document.content_type or "application/pdf",
    )


def _save_form_builder_metadata(form_definition: Form, *, user):
    form_definition.updated_by = user
    if form_definition.status == Form.PublicationStatus.PUBLISHED:
        form_definition.published_at = form_definition.published_at or timezone.now()
        form_definition.full_clean()
        with transaction.atomic():
            Form.objects.filter(
                key=form_definition.key,
                status=Form.PublicationStatus.PUBLISHED,
            ).exclude(pk=form_definition.pk).update(
                status=Form.PublicationStatus.RETIRED,
                published_at=None,
            )
            form_definition.save()
        return
    form_definition.save()


def _next_form_version(form_key: str) -> int:
    versions = Form.objects.filter(key=form_key).values_list("version", flat=True)
    return (max(versions) + 1) if versions else 1


def _require_form_builder_editable(form_definition: Form) -> None:
    if form_definition.status == Form.PublicationStatus.PUBLISHED:
        raise PermissionDenied("Veroeffentlichte Formulare sind im Builder schreibgeschuetzt.")


def _sync_builder_form(form_definition: Form) -> None:
    form_definition.sync_schema()


def _create_draft_version_from_form(source: Form, *, user) -> Form:
    """Create a safe editable draft version from a locked/published form."""
    with transaction.atomic():
        draft = Form.objects.create(
            key=source.key,
            version=_next_form_version(source.key),
            title=source.title,
            description=source.description,
            org_unit=source.org_unit,
            status=Form.PublicationStatus.DRAFT,
            is_archivable=source.is_archivable,
            review_required=source.review_required,
            retention_period_days=source.retention_period_days,
            supersedes=source,
            created_by=user,
            updated_by=user,
        )

        section_map = {}
        for old_section in source.sections.order_by("position", "title"):
            new_section = FormSection.objects.create(
                form=draft,
                title=old_section.title,
                description=old_section.description,
                position=old_section.position,
                is_collapsible=old_section.is_collapsible,
                is_active=old_section.is_active,
                created_by=user,
                updated_by=user,
            )
            section_map[old_section.pk] = new_section

        field_map = {}
        for old_field in source.fields.order_by("position", "key"):
            new_field = Field.objects.create(
                form=draft,
                section=section_map.get(old_field.section_id),
                key=old_field.key,
                label=old_field.label,
                help_text=old_field.help_text,
                field_type=old_field.field_type,
                position=old_field.position,
                required=old_field.required,
                placeholder=old_field.placeholder,
                choices=old_field.choices,
                validation_rules=old_field.validation_rules,
                ui_config=old_field.ui_config,
                is_active=old_field.is_active,
                sensitivity=old_field.sensitivity,
                created_by=user,
                updated_by=user,
            )
            field_map[old_field.pk] = new_field

        group_map = {}
        for old_group in source.repeatable_groups.order_by("position", "title"):
            new_group = RepeatableGroup.objects.create(
                form=draft,
                section=section_map.get(old_group.section_id),
                key=old_group.key,
                title=old_group.title,
                description=old_group.description,
                position=old_group.position,
                min_rows=old_group.min_rows,
                max_rows=old_group.max_rows,
                is_active=old_group.is_active,
                ui_config=old_group.ui_config,
                created_by=user,
                updated_by=user,
            )
            group_map[old_group.pk] = new_group
            for old_column in old_group.columns.order_by("position", "key"):
                RepeatableGroupColumn.objects.create(
                    group=new_group,
                    key=old_column.key,
                    label=old_column.label,
                    help_text=old_column.help_text,
                    column_type=old_column.column_type,
                    position=old_column.position,
                    required=old_column.required,
                    placeholder=old_column.placeholder,
                    choices=old_column.choices,
                    validation_rules=old_column.validation_rules,
                    ui_config=old_column.ui_config,
                    is_active=old_column.is_active,
                    created_by=user,
                    updated_by=user,
                )

        for old_rule in source.conditional_rules.order_by("created_at"):
            ConditionalRule.objects.create(
                form=draft,
                source_field=field_map[old_rule.source_field_id],
                operator=old_rule.operator,
                value=old_rule.value,
                action=old_rule.action,
                target_field=field_map.get(old_rule.target_field_id),
                target_section=section_map.get(old_rule.target_section_id),
                message=old_rule.message,
                is_active=old_rule.is_active,
                created_by=user,
                updated_by=user,
            )

        for old_rule in source.action_item_rules.order_by("name"):
            ActionItemRule.objects.create(
                form=draft,
                name=old_rule.name,
                source_field=field_map.get(old_rule.source_field_id),
                source_field_key=old_rule.source_field_key,
                source_group_key=old_rule.source_group_key,
                source_column_key=old_rule.source_column_key,
                operator=old_rule.operator,
                value=old_rule.value,
                title_template=old_rule.title_template,
                description_template=old_rule.description_template,
                assigned_to=old_rule.assigned_to,
                assigned_to_field_key=old_rule.assigned_to_field_key,
                due_at_field_key=old_rule.due_at_field_key,
                priority=old_rule.priority,
                is_active=old_rule.is_active,
                config=old_rule.config,
                created_by=user,
                updated_by=user,
            )

        draft.sync_schema()
        return draft


@login_required(login_url="login")
def form_builder_create_draft_version_view(request, form_id):
    require_permission(can_manage_settings(request.user))
    source = get_object_or_404(Form, pk=form_id)
    if request.method != "POST":
        return redirect("form_builder:form_builder_edit", source.pk)
    draft = _create_draft_version_from_form(source, user=request.user)
    messages.success(
        request,
        f"Neue bearbeitbare Entwurfs-Version v{draft.version} wurde erstellt.",
    )
    return redirect("form_builder:form_builder_edit", draft.pk)


@login_required(login_url="login")
def form_builder_list_view(request):
    require_permission(can_manage_settings(request.user))
    forms = Form.objects.prefetch_related("sections", "fields").order_by("title", "key", "-version")
    context = build_app_context(
        request,
        title="Formular-Builder",
        current_url_name="form_builder:form_builder_list",
        forms=forms,
    )
    return render(request, "form_builder/settings/form_builder_list.html", context)


@login_required(login_url="login")
def form_builder_create_view(request):
    require_permission(can_manage_settings(request.user))
    if request.method == "POST":
        builder_form = FormBuilderMetadataForm(request.POST)
        if builder_form.is_valid():
            form_definition = builder_form.save(commit=False)
            form_definition.created_by = request.user
            if not form_definition.version:
                form_definition.version = _next_form_version(form_definition.key)
            _save_form_builder_metadata(form_definition, user=request.user)
            _sync_builder_form(form_definition)
            messages.success(
                request,
                "Formular wurde angelegt. Abschnitte und Felder koennen jetzt erfasst werden.",
            )
            return redirect("form_builder:form_builder_edit", form_definition.pk)
        messages.error(request, "Formular konnte nicht angelegt werden. Bitte Eingaben pruefen.")
    else:
        builder_form = FormBuilderMetadataForm(initial={"version": 1})
    context = build_app_context(
        request,
        title="Formular anlegen",
        current_url_name="form_builder:form_builder_list",
        builder_form=builder_form,
        mode="create",
    )
    return render(request, "form_builder/settings/form_builder_form.html", context)


@login_required(login_url="login")
def form_builder_edit_view(request, form_id):
    require_permission(can_manage_settings(request.user))
    form_definition = get_object_or_404(
        Form.objects.prefetch_related("sections", "fields"), pk=form_id
    )
    is_locked = form_definition.status == Form.PublicationStatus.PUBLISHED
    if request.method == "POST":
        _require_form_builder_editable(form_definition)
        builder_form = FormBuilderMetadataForm(request.POST, instance=form_definition)
        if builder_form.is_valid():
            form_definition = builder_form.save(commit=False)
            _save_form_builder_metadata(form_definition, user=request.user)
            _sync_builder_form(form_definition)
            messages.success(request, "Formular-Metadaten wurden gespeichert.")
            return redirect("form_builder:form_builder_edit", form_definition.pk)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        builder_form = FormBuilderMetadataForm(instance=form_definition)
    context = build_app_context(
        request,
        title="Formular bearbeiten",
        current_url_name="form_builder:form_builder_list",
        builder_form=builder_form,
        form_definition=form_definition,
        sections=form_definition.sections.all().order_by("position", "title"),
        unsectioned_fields=form_definition.fields.filter(section__isnull=True).order_by(
            "position", "key"
        ),
        is_locked=is_locked,
        mode="edit",
    )
    return render(request, "form_builder/settings/form_builder_form.html", context)


@login_required(login_url="login")
def form_section_create_view(request, form_id):
    require_permission(can_manage_settings(request.user))
    form_definition = get_object_or_404(Form, pk=form_id)
    _require_form_builder_editable(form_definition)
    if request.method == "POST":
        section_form = FormSectionBuilderForm(request.POST, form_definition=form_definition)
        section_form.instance.form = form_definition
        if section_form.is_valid():
            section = section_form.save(commit=False)
            section.form = form_definition
            section.created_by = request.user
            section.updated_by = request.user
            section.save()
            _sync_builder_form(form_definition)
            messages.success(request, "Abschnitt wurde gespeichert.")
            return redirect("form_builder:form_builder_edit", form_definition.pk)
        messages.error(request, "Abschnitt konnte nicht gespeichert werden.")
    else:
        next_position = (
            form_definition.sections.order_by("-position")
            .values_list("position", flat=True)
            .first()
            or 0
        ) + 1
        section_form = FormSectionBuilderForm(
            initial={"position": next_position, "is_active": True},
            form_definition=form_definition,
        )
    context = build_app_context(
        request,
        title="Abschnitt anlegen",
        current_url_name="form_builder:form_builder_list",
        form_definition=form_definition,
        section_form=section_form,
        mode="create",
    )
    return render(request, "form_builder/settings/form_section_form.html", context)


@login_required(login_url="login")
def form_section_edit_view(request, section_id):
    require_permission(can_manage_settings(request.user))
    section = get_object_or_404(FormSection.objects.select_related("form"), pk=section_id)
    _require_form_builder_editable(section.form)
    if request.method == "POST":
        section_form = FormSectionBuilderForm(
            request.POST, instance=section, form_definition=section.form
        )
        if section_form.is_valid():
            section = section_form.save(commit=False)
            section.updated_by = request.user
            section.save()
            _sync_builder_form(section.form)
            messages.success(request, "Abschnitt wurde aktualisiert.")
            return redirect("form_builder:form_builder_edit", section.form_id)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        section_form = FormSectionBuilderForm(instance=section, form_definition=section.form)
    context = build_app_context(
        request,
        title="Abschnitt bearbeiten",
        current_url_name="form_builder:form_builder_list",
        form_definition=section.form,
        section=section,
        section_form=section_form,
        mode="edit",
    )
    return render(request, "form_builder/settings/form_section_form.html", context)


@login_required(login_url="login")
def form_section_delete_view(request, section_id):
    require_permission(can_manage_settings(request.user))
    section = get_object_or_404(FormSection.objects.select_related("form"), pk=section_id)
    form_definition = section.form
    _require_form_builder_editable(form_definition)
    if request.method != "POST":
        return redirect("form_builder:form_builder_edit", form_definition.pk)
    form = ConfirmDeleteForm(request.POST)
    if form.is_valid():
        section.delete()
        _sync_builder_form(form_definition)
        messages.success(
            request,
            "Abschnitt wurde geloescht. Zugeordnete Felder bleiben ohne Abschnitt erhalten.",
        )
    return redirect("form_builder:form_builder_edit", form_definition.pk)


def _swap_section_position(section: FormSection, direction: str) -> None:
    queryset = FormSection.objects.filter(form=section.form).order_by("position", "title")
    sections = list(queryset)
    index = sections.index(section)
    target_index = index - 1 if direction == "up" else index + 1
    if target_index < 0 or target_index >= len(sections):
        return
    target = sections[target_index]
    temporary_position = max(item.position for item in sections) + 1
    with transaction.atomic():
        FormSection.objects.filter(pk=section.pk).update(position=temporary_position)
        FormSection.objects.filter(pk=target.pk).update(position=section.position)
        FormSection.objects.filter(pk=section.pk).update(position=target.position)


@login_required(login_url="login")
def form_section_reorder_view(request, section_id, direction):
    require_permission(can_manage_settings(request.user))
    section = get_object_or_404(FormSection.objects.select_related("form"), pk=section_id)
    _require_form_builder_editable(section.form)
    if request.method == "POST" and direction in {"up", "down"}:
        _swap_section_position(section, direction)
        _sync_builder_form(section.form)
    return redirect("form_builder:form_builder_edit", section.form_id)


@login_required(login_url="login")
def form_field_create_view(request, form_id):
    require_permission(can_manage_settings(request.user))
    form_definition = get_object_or_404(Form, pk=form_id)
    _require_form_builder_editable(form_definition)
    initial = {}
    section_id = request.GET.get("section") or request.POST.get("section")
    if section_id:
        initial["section"] = section_id
    if request.method == "POST":
        field_form = FieldBuilderForm(request.POST, form_definition=form_definition)
        if field_form.is_valid():
            field = field_form.save(commit=False)
            field.created_by = request.user
            field.updated_by = request.user
            field.save()
            _sync_builder_form(form_definition)
            messages.success(request, "Feld wurde gespeichert.")
            return redirect("form_builder:form_builder_edit", form_definition.pk)
        messages.error(request, "Feld konnte nicht gespeichert werden. Bitte Eingaben pruefen.")
    else:
        field_form = FieldBuilderForm(form_definition=form_definition, initial=initial)
    context = build_app_context(
        request,
        title="Feld anlegen",
        current_url_name="form_builder:form_builder_list",
        form_definition=form_definition,
        field_form=field_form,
        mode="create",
    )
    return render(request, "form_builder/settings/form_field_form.html", context)


@login_required(login_url="login")
def form_field_edit_view(request, field_id):
    require_permission(can_manage_settings(request.user))
    field = get_object_or_404(Field.objects.select_related("form", "section"), pk=field_id)
    _require_form_builder_editable(field.form)
    if request.method == "POST":
        field_form = FieldBuilderForm(request.POST, form_definition=field.form, instance=field)
        if field_form.is_valid():
            field = field_form.save(commit=False)
            field.updated_by = request.user
            field.save()
            _sync_builder_form(field.form)
            messages.success(request, "Feld wurde aktualisiert.")
            return redirect("form_builder:form_builder_edit", field.form_id)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        field_form = FieldBuilderForm(form_definition=field.form, instance=field)
    context = build_app_context(
        request,
        title="Feld bearbeiten",
        current_url_name="form_builder:form_builder_list",
        form_definition=field.form,
        field=field,
        field_form=field_form,
        mode="edit",
    )
    return render(request, "form_builder/settings/form_field_form.html", context)


@login_required(login_url="login")
def form_field_delete_view(request, field_id):
    require_permission(can_manage_settings(request.user))
    field = get_object_or_404(Field.objects.select_related("form"), pk=field_id)
    form_definition = field.form
    _require_form_builder_editable(form_definition)
    if request.method != "POST":
        return redirect("form_builder:form_builder_edit", form_definition.pk)
    form = ConfirmDeleteForm(request.POST)
    if form.is_valid():
        field.delete()
        _sync_builder_form(form_definition)
        messages.success(request, "Feld wurde geloescht.")
    return redirect("form_builder:form_builder_edit", form_definition.pk)


def _swap_field_position(field: Field, direction: str) -> None:
    queryset = Field.objects.filter(form=field.form, section=field.section).order_by(
        "position", "key"
    )
    fields = list(queryset)
    index = fields.index(field)
    target_index = index - 1 if direction == "up" else index + 1
    if target_index < 0 or target_index >= len(fields):
        return
    target = fields[target_index]
    positions = list(Field.objects.filter(form=field.form).values_list("position", flat=True))
    temporary_position = (max(positions) if positions else 0) + 1
    with transaction.atomic():
        Field.objects.filter(pk=field.pk).update(position=temporary_position)
        Field.objects.filter(pk=target.pk).update(position=field.position)
        Field.objects.filter(pk=field.pk).update(position=target.position)


@login_required(login_url="login")
def form_field_reorder_view(request, field_id, direction):
    require_permission(can_manage_settings(request.user))
    field = get_object_or_404(Field.objects.select_related("form", "section"), pk=field_id)
    _require_form_builder_editable(field.form)
    if request.method == "POST" and direction in {"up", "down"}:
        _swap_field_position(field, direction)
        _sync_builder_form(field.form)
    return redirect("form_builder:form_builder_edit", field.form_id)
