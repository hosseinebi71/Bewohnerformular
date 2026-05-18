import logging
from types import SimpleNamespace
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import FormRecipientSettingsForm, UserAccessProfileForm
from .mail_services import process_outbox_queue
from .models import (
    AuditLog,
    Form,
    FormEntry,
    FormRecipient,
    FormSchedule,
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
