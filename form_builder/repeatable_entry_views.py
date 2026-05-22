from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .action_item_services import sync_action_items_for_entry
from .conditional_services import apply_conditional_rules_to_form, get_conditional_rules_payload
from .models import Form, FormEntry
from .pdf_services import get_latest_generated_pdf_document
from .permissions import (
    can_create_entries,
    can_edit_entry,
    can_review_entry,
    can_send_entry,
    can_view_forms,
)
from .repeatable_services import (
    apply_repeatable_payload,
    get_augmented_form_schema,
    repeatable_tables_for_entry,
)
from .services import (
    build_entry_form,
    build_entry_form_for_entry,
    create_form_entry_from_validated,
    get_entry_attachments,
    save_draft_from_validated,
    submit_draft_for_review,
    validate_draft,
)
from .views import (
    EDITABLE_ENTRY_STATUSES,
    build_app_context,
    render_entry_response,
    require_entry_permission,
    require_permission,
)


def _conditional_rules_for(form_definition: Form) -> list[dict]:
    return get_conditional_rules_payload(form_definition)


def _apply_conditional_validation(
    *, entry_form, form_definition: Form, schema: dict, request, form_entry: FormEntry | None = None
) -> bool:
    return apply_conditional_rules_to_form(
        form=entry_form,
        form_definition=form_definition,
        schema=schema,
        cleaned_data=entry_form.cleaned_data,
        uploaded_files=request.FILES,
        form_entry=form_entry,
    )


def _entry_detail_rows(form_entry: FormEntry) -> list[dict]:
    rows = []
    attachments_by_key = {
        attachment.field_key: attachment for attachment in get_entry_attachments(form_entry)
    }
    for field_definition in form_entry.form_snapshot.get("fields", []):
        key = field_definition.get("key")
        value = form_entry.data.get(key, "-")
        attachment = attachments_by_key.get(key)
        is_signature = (field_definition.get("ui_config") or {}).get("widget") == "signature"
        if is_signature:
            if isinstance(value, dict) and value.get("signature_hash"):
                signed_at = value.get("signed_at", "")
                signed_by = value.get("signed_by", "") or "-"
                value = f"Unterschrieben ({signed_by}, {signed_at[:16]})"
            elif value not in (None, ""):
                value = "Unterschrieben"
            else:
                value = "-"
        elif attachment:
            value = attachment.original_filename
        elif isinstance(value, dict) and value.get("filename"):
            value = value.get("filename")
        elif isinstance(value, list):
            value = ", ".join(str(item) for item in value) or "-"
        if value in (None, ""):
            value = "-"
        rows.append(
            {
                "label": field_definition.get("label", key or "Feld"),
                "value": value,
                "field_type": field_definition.get("field_type", "text"),
                "sensitivity": field_definition.get("sensitivity", "normal"),
                "attachment": attachment,
                "is_signature": is_signature,
            }
        )
    return rows


@login_required(login_url="login")
def entry_create_view(request, form_id):
    require_permission(can_create_entries(request.user))
    form_definition = get_object_or_404(Form, pk=form_id, status=Form.PublicationStatus.PUBLISHED)
    schema = get_augmented_form_schema(form_definition)
    form_definition.schema = schema
    if request.method == "POST":
        entry_form = build_entry_form(
            form_definition, data=request.POST, files=request.FILES, include_bewohner=False
        )
        if entry_form.is_valid() and _apply_conditional_validation(
            entry_form=entry_form,
            form_definition=form_definition,
            schema=schema,
            request=request,
        ):
            try:
                form_entry = create_form_entry_from_validated(
                    form_definition=form_definition,
                    cleaned_data=entry_form.cleaned_data,
                    user=request.user,
                    uploaded_files=request.FILES,
                )
                apply_repeatable_payload(
                    form_entry=form_entry,
                    post_data=request.POST,
                    files=request.FILES,
                    user=request.user,
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
            conditional_rules=_conditional_rules_for(form_definition),
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
        FormEntry.objects.select_related(
            "form", "bewohner", "created_by", "updated_by", "locked_by"
        ),
        pk=entry_id,
    )
    require_entry_permission(request.user, form_entry, action="edit")
    if form_entry.status not in EDITABLE_ENTRY_STATUSES:
        messages.info(request, "Dieser Eintrag ist nicht mehr im Entwurfsmodus bearbeitbar.")
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    form_entry.form_snapshot = form_entry.form_snapshot or get_augmented_form_schema(
        form_entry.form
    )
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
            conditional_rules=_conditional_rules_for(form_entry.form),
            pdf_inline_url=None,
        ),
    )


def _schema_for_entry(form_entry: FormEntry) -> dict:
    return form_entry.form_snapshot or get_augmented_form_schema(form_entry.form)


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
    schema = _schema_for_entry(form_entry)
    entry_form = build_entry_form_for_entry(form_entry, data=request.POST, files=request.FILES)
    if entry_form.is_valid() and _apply_conditional_validation(
        entry_form=entry_form,
        form_definition=form_entry.form,
        schema=schema,
        request=request,
        form_entry=form_entry,
    ):
        try:
            save_draft_from_validated(
                form_entry=form_entry,
                cleaned_data=entry_form.cleaned_data,
                user=request.user,
                uploaded_files=request.FILES,
            )
            apply_repeatable_payload(
                form_entry=form_entry,
                post_data=request.POST,
                files=request.FILES,
                user=request.user,
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
            conditional_rules=_conditional_rules_for(form_entry.form),
        ),
        status=400,
    )


@login_required(login_url="login")
def entry_validate_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner"), pk=entry_id
    )
    require_entry_permission(request.user, form_entry, action="edit")
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
    schema = _schema_for_entry(form_entry)
    entry_form = build_entry_form_for_entry(form_entry, data=request.POST, files=request.FILES)
    if entry_form.is_valid() and _apply_conditional_validation(
        entry_form=entry_form,
        form_definition=form_entry.form,
        schema=schema,
        request=request,
        form_entry=form_entry,
    ):
        try:
            validate_draft(
                form_entry=form_entry,
                cleaned_data=entry_form.cleaned_data,
                user=request.user,
                uploaded_files=request.FILES,
            )
            apply_repeatable_payload(
                form_entry=form_entry,
                post_data=request.POST,
                files=request.FILES,
                user=request.user,
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
            conditional_rules=_conditional_rules_for(form_entry.form),
        ),
        status=400,
    )


@login_required(login_url="login")
def entry_review_view(request, entry_id):
    require_permission(can_create_entries(request.user))
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner"), pk=entry_id
    )
    require_entry_permission(request.user, form_entry, action="edit")
    if request.method != "POST":
        return redirect("form_builder:entry_edit", entry_id=form_entry.pk)
    schema = _schema_for_entry(form_entry)
    entry_form = build_entry_form_for_entry(form_entry, data=request.POST, files=request.FILES)
    if entry_form.is_valid() and _apply_conditional_validation(
        entry_form=entry_form,
        form_definition=form_entry.form,
        schema=schema,
        request=request,
        form_entry=form_entry,
    ):
        try:
            submit_draft_for_review(
                form_entry=form_entry,
                cleaned_data=entry_form.cleaned_data,
                user=request.user,
                uploaded_files=request.FILES,
            )
            apply_repeatable_payload(
                form_entry=form_entry,
                post_data=request.POST,
                files=request.FILES,
                user=request.user,
            )
            sync_action_items_for_entry(form_entry=form_entry, user=request.user)
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
            conditional_rules=_conditional_rules_for(form_entry.form),
        ),
        status=400,
    )
