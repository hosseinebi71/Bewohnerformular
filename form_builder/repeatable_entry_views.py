from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .attachment_entry_views import (
    EDITABLE_ENTRY_STATUSES,
    build_app_context,
    _entry_detail_rows,
    render_entry_response,
    require_entry_permission,
    require_permission,
)
from .models import Form, FormEntry
from .permissions import can_create_entries, can_edit_entry, can_review_entry, can_send_entry, can_view_forms
from .pdf_services import get_latest_generated_pdf_document
from .services import get_entry_attachments
from .repeatable_services import (
    apply_repeatable_payload,
    get_augmented_form_schema,
    repeatable_tables_for_entry,
)
from .services import (
    build_entry_form,
    build_entry_form_for_entry,
    create_form_entry_from_validated,
    save_draft_from_validated,
    submit_draft_for_review,
    validate_draft,
)


@login_required(login_url="login")
def entry_create_view(request, form_id):
    require_permission(can_create_entries(request.user))
    form_definition = get_object_or_404(Form, pk=form_id, status=Form.PublicationStatus.PUBLISHED)
    form_definition.schema = get_augmented_form_schema(form_definition)
    if request.method == "POST":
        entry_form = build_entry_form(
            form_definition, data=request.POST, files=request.FILES, include_bewohner=False
        )
        if entry_form.is_valid():
            try:
                form_entry = create_form_entry_from_validated(
                    form_definition=form_definition,
                    cleaned_data=entry_form.cleaned_data,
                    user=request.user,
                    uploaded_files=request.FILES,
                )
                apply_repeatable_payload(
                    form_entry=form_entry, post_data=request.POST, files=request.FILES, user=request.user
                )
            except ValidationError as exc:
                entry_form.add_error(None, exc)
            else:
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
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by"), pk=entry_id
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
            detail_rows=_entry_detail_rows(form_entry),
            repeatable_tables=repeatable_tables_for_entry(form_entry),
            attachments=get_entry_attachments(form_entry),
            can_edit_entry=can_edit_entry(request.user, form_entry)
            and form_entry.status in EDITABLE_ENTRY_STATUSES,
            can_review_entry=can_review_entry(request.user, form_entry)
            and form_entry.status == FormEntry.EntryStatus.IN_REVIEW,
            can_queue_entry=can_send_entry(request.user, form_entry)
            and form_entry.status == FormEntry.EntryStatus.APPROVED,
            can_send_entry=can_send_entry(request.user, form_entry)
            and form_entry.status == FormEntry.EntryStatus.APPROVED,
            latest_pdf_document=get_latest_generated_pdf_document(form_entry),
        ),
    )


@login_required(login_url="login")
def entry_edit_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by", "locked_by"),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="edit")
    if form_entry.status not in EDITABLE_ENTRY_STATUSES:
        messages.info(request, "Dieser Eintrag ist nicht mehr im Entwurfsmodus bearbeitbar.")
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    form_entry.form_snapshot = form_entry.form_snapshot or get_augmented_form_schema(form_entry.form)
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
            attachments=get_entry_attachments(form_entry),
            repeatable_tables=repeatable_tables_for_entry(form_entry),
            pdf_inline_url=None,
        ),
    )


@login_required(login_url="login")
def entry_save_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by", "locked_by"),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="edit")
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
    if form_entry.status not in EDITABLE_ENTRY_STATUSES:
        messages.error(request, "Dieser Eintrag kann nicht mehr als Entwurf gespeichert werden.")
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    entry_form = build_entry_form_for_entry(form_entry, data=request.POST, files=request.FILES)
    if entry_form.is_valid():
        try:
            save_draft_from_validated(
                form_entry=form_entry,
                cleaned_data=entry_form.cleaned_data,
                user=request.user,
                uploaded_files=request.FILES,
            )
            apply_repeatable_payload(
                form_entry=form_entry, post_data=request.POST, files=request.FILES, user=request.user
            )
        except ValidationError as exc:
            entry_form.add_error(None, exc)
        else:
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
            attachments=get_entry_attachments(form_entry),
            repeatable_tables=repeatable_tables_for_entry(form_entry),
        ),
        status=400,
    )


@login_required(login_url="login")
def entry_validate_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(FormEntry.objects.select_related("form", "bewohner"), pk=entry_id)
    require_entry_permission(request.user, form_entry, action="edit")
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
    entry_form = build_entry_form_for_entry(form_entry, data=request.POST, files=request.FILES)
    if entry_form.is_valid():
        try:
            validate_draft(
                form_entry=form_entry,
                cleaned_data=entry_form.cleaned_data,
                user=request.user,
                uploaded_files=request.FILES,
            )
            apply_repeatable_payload(
                form_entry=form_entry, post_data=request.POST, files=request.FILES, user=request.user
            )
        except ValidationError as exc:
            entry_form.add_error(None, exc)
        else:
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
            attachments=get_entry_attachments(form_entry),
            repeatable_tables=repeatable_tables_for_entry(form_entry),
        ),
        status=400,
    )


@login_required(login_url="login")
def entry_review_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(FormEntry.objects.select_related("form", "bewohner"), pk=entry_id)
    require_entry_permission(request.user, form_entry, action="edit")
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
    entry_form = build_entry_form_for_entry(form_entry, data=request.POST, files=request.FILES)
    if entry_form.is_valid():
        try:
            submit_draft_for_review(
                form_entry=form_entry,
                cleaned_data=entry_form.cleaned_data,
                user=request.user,
                uploaded_files=request.FILES,
            )
            apply_repeatable_payload(
                form_entry=form_entry, post_data=request.POST, files=request.FILES, user=request.user
            )
        except ValidationError as exc:
            entry_form.add_error(None, exc)
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
            attachments=get_entry_attachments(form_entry),
            repeatable_tables=repeatable_tables_for_entry(form_entry),
        ),
        status=400,
    )
