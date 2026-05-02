from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from .models import AuditLog, Form, FormEntry, FormSchedule, PDFDocument
from .navigation import get_navigation_items
from .permissions import (
    can_create_entries,
    can_manage_settings,
    can_review_entries,
    can_send_entries,
    can_view_dashboard,
    can_view_forms,
    can_view_settings,
)
from .selectors import (
    get_archive_queryset,
    get_available_forms_queryset,
    get_dashboard_counts,
    get_entries_in_review_queryset,
    get_frequent_forms,
    get_outbox_pending_queryset,
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
from .pdf_services import (
    generate_entry_pdf_document,
    get_latest_generated_pdf_document,
    get_pdf_private_path,
    render_entry_pdf_html,
)
from .mail_services import process_outbox_queue
from .schedule_forms import FormScheduleForm
from .schedule_services import run_due_schedules

EDITABLE_ENTRY_STATUSES = {
    FormEntry.EntryStatus.DRAFT,
    FormEntry.EntryStatus.REJECTED,
}


def require_permission(condition: bool):
    if not condition:
        raise PermissionDenied


def build_app_context(request, *, title: str, current_url_name: str, **extra):
    return {
        "page_title": title,
        "navigation_items": get_navigation_items(request.user, current_url_name=current_url_name),
        "current_url_name": current_url_name,
        **extra,
    }


def render_entry_response(request, template_name, context, status=200):
    return render(request, template_name, context, status=status)


def get_entry_detail_rows(form_entry: FormEntry) -> list[dict]:
    detail_rows = []
    for field_definition in form_entry.form_snapshot.get("fields", []):
        value = form_entry.data.get(field_definition["key"], "-")
        if isinstance(value, list):
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
        frequent_forms=get_frequent_forms(),
        recent_activity=get_recent_activity(),
    )
    return render(request, "form_builder/dashboard.html", context)


@login_required(login_url="login")
def form_list_view(request):
    require_permission(can_view_forms(request.user))
    context = build_app_context(
        request,
        title="Formulare",
        current_url_name="form_builder:form_list",
        forms=get_available_forms_queryset(),
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
        entries=get_entries_in_review_queryset(),
    )
    return render(request, "form_builder/review_list.html", context)


@login_required(login_url="login")
def outbox_list_view(request):
    require_permission(can_view_forms(request.user))
    context = build_app_context(
        request,
        title="Ausgangskorb",
        current_url_name="form_builder:outbox_list",
        items=get_outbox_pending_queryset(),
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
        items=get_sent_outbox_queryset(),
    )
    return render(request, "form_builder/sent_list.html", context)


@login_required(login_url="login")
def archive_list_view(request):
    require_permission(can_view_forms(request.user))
    context = build_app_context(
        request,
        title="Archiv",
        current_url_name="form_builder:archive_list",
        items=get_archive_queryset(),
    )
    return render(request, "form_builder/archive_list.html", context)


@login_required(login_url="login")
def profile_view(request):
    context = build_app_context(
        request,
        title="Profil",
        current_url_name="form_builder:profile",
        audit_logs=(
            request.user.form_audit_logs.select_related("form", "bewohner", "form_entry")
            .order_by("-occurred_at")[:10]
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
        active_recipients=request.user.form_builder_formrecipient_created.count()
        if hasattr(request.user, "form_builder_formrecipient_created")
        else 0,
        active_schedules=request.user.form_builder_formschedule_created.count()
        if hasattr(request.user, "form_builder_formschedule_created")
        else 0,
        pending_outbox=get_outbox_pending_queryset().count(),
        available_forms=get_available_forms_queryset().count(),
    )
    return render(request, "form_builder/settings/index.html", context)


@login_required(login_url="login")
def schedule_list_view(request):
    require_permission(can_view_settings(request.user))
    schedules = FormSchedule.objects.select_related("form").order_by("form__title", "name")
    context = build_app_context(request, title="Zeitplaene", current_url_name="form_builder:schedule_list", schedules=schedules, can_manage_settings=can_manage_settings(request.user))
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
            messages.success(request, "Zeitplan wurde angelegt.")
            return redirect("form_builder:schedule_list")
        messages.error(request, "Zeitplan konnte nicht gespeichert werden. Bitte Eingaben pruefen.")
    else:
        form = FormScheduleForm()
    context = build_app_context(request, title="Zeitplan anlegen", current_url_name="form_builder:schedule_list", schedule_form=form, mode="create")
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
            messages.success(request, "Zeitplan wurde aktualisiert.")
            return redirect("form_builder:schedule_list")
        messages.error(request, "Zeitplan konnte nicht aktualisiert werden. Bitte Eingaben pruefen.")
    else:
        form = FormScheduleForm(instance=schedule)
    context = build_app_context(request, title="Zeitplan bearbeiten", current_url_name="form_builder:schedule_list", schedule=schedule, schedule_form=form, mode="edit")
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
    if result.errors:
        messages.warning(request, result.summary_de() + " Bitte Details im Server-Log pruefen.")
    elif result.queued:
        messages.success(request, result.summary_de())
    else:
        messages.info(request, result.summary_de())
    return redirect("form_builder:schedule_list")


@login_required(login_url="login")
def entry_create_view(request, form_id):
    require_permission(can_create_entries(request.user))
    form_definition = get_object_or_404(
        Form,
        pk=form_id,
        status=Form.PublicationStatus.PUBLISHED,
    )
    if request.method == "POST":
        entry_form = build_entry_form(form_definition, data=request.POST, include_bewohner=True)
        if entry_form.is_valid():
            bewohner = entry_form.cleaned_data["bewohner"]
            form_entry = create_form_entry_from_validated(
                form_definition=form_definition,
                bewohner=bewohner,
                cleaned_data=entry_form.cleaned_data,
                user=request.user,
            )
            messages.success(request, "Entwurf wurde angelegt.")
            return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
        messages.error(request, "Bitte pruefe die Eingaben.")
    else:
        entry_form = build_entry_form(form_definition, include_bewohner=True)

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
    return render(
        request,
        "form_builder/entry_detail.html",
        build_app_context(
            request,
            title="Formulareintrag",
            current_url_name="form_builder:draft_list",
            form_entry=form_entry,
            detail_rows=get_entry_detail_rows(form_entry),
            can_edit_entry=can_create_entries(request.user) and form_entry.status in EDITABLE_ENTRY_STATUSES,
            can_review_entry=can_review_entries(request.user) and form_entry.status == FormEntry.EntryStatus.IN_REVIEW,
            can_queue_entry=can_send_entries(request.user) and form_entry.status == FormEntry.EntryStatus.APPROVED,
            latest_pdf_document=get_latest_generated_pdf_document(form_entry),
        ),
    )


@login_required(login_url="login")
def entry_edit_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner"),
        pk=entry_id,
    )
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
        ),
    )


@login_required(login_url="login")
def entry_save_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(FormEntry.objects.select_related("form", "bewohner"), pk=entry_id)
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
def entry_validate_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(FormEntry.objects.select_related("form", "bewohner"), pk=entry_id)
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
    form_entry = get_object_or_404(FormEntry.objects.select_related("form", "bewohner"), pk=entry_id)
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
    form_entry = get_object_or_404(FormEntry.objects.select_related("form", "bewohner"), pk=entry_id)
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
    form_entry = get_object_or_404(FormEntry.objects.select_related("form", "bewohner"), pk=entry_id)
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
    form_entry = get_object_or_404(FormEntry.objects.select_related("form", "bewohner"), pk=entry_id)
    if request.method != "POST":
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    try:
        created_items = queue_entry_for_delivery(form_entry=form_entry, user=request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f"{len(created_items)} Versandvorgang wurde in den Ausgangskorb gestellt.")
        return redirect("form_builder:outbox_list")
    return redirect("form_builder:entry_detail", entry_id=form_entry.pk)


@login_required(login_url="login")
def entry_pdf_preview_view(request, entry_id):
    require_permission(can_view_forms(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by"),
        pk=entry_id,
    )
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
def entry_pdf_generate_view(request, entry_id):
    require_permission(can_review_entries(request.user) or can_send_entries(request.user))
    form_entry = get_object_or_404(FormEntry.objects.select_related("form", "bewohner"), pk=entry_id)
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
