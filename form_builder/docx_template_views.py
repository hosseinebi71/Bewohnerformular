from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render

from .docx_template_forms import DOCXTemplateStatusForm, DOCXTemplateUploadForm
from .docx_template_models import DOCXTemplate
from .docx_template_services import create_docx_template, generate_docx_document
from .models import FormEntry
from .pdf_services import get_pdf_private_path
from .permissions import can_manage_settings, can_send_entry, can_view_entry, can_view_settings
from .views import build_app_context, require_permission


@login_required(login_url="login")
def docx_template_list_view(request):
    require_permission(can_view_settings(request.user))
    templates = DOCXTemplate.objects.select_related("form", "uploaded_by").order_by(
        "form__title", "-created_at"
    )
    return render(
        request,
        "form_builder/docx_templates/list.html",
        build_app_context(
            request,
            title="DOCX-Vorlagen",
            current_url_name="form_builder:docx_template_list",
            templates=templates,
            can_manage_settings=can_manage_settings(request.user),
        ),
    )


@login_required(login_url="login")
def docx_template_upload_view(request):
    require_permission(can_manage_settings(request.user))
    if request.method == "POST":
        form = DOCXTemplateUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                template = create_docx_template(
                    form=form.cleaned_data["form"],
                    uploaded_file=form.cleaned_data["template_file"],
                    title=form.cleaned_data["title"],
                    description=form.cleaned_data.get("description", ""),
                    user=request.user,
                )
                if form.cleaned_data.get("make_default"):
                    template.activate(user=request.user)
            except ValidationError as exc:
                form.add_error(None, exc.message if hasattr(exc, "message") else exc)
            else:
                messages.success(request, "DOCX-Vorlage wurde hochgeladen.")
                return redirect("form_builder:docx_template_detail", template_id=template.pk)
        messages.error(
            request, "DOCX-Vorlage konnte nicht gespeichert werden. Bitte Eingaben pruefen."
        )
    else:
        form = DOCXTemplateUploadForm()
    return render(
        request,
        "form_builder/docx_templates/upload.html",
        build_app_context(
            request,
            title="DOCX-Vorlage hochladen",
            current_url_name="form_builder:docx_template_list",
            upload_form=form,
        ),
    )


@login_required(login_url="login")
def docx_template_detail_view(request, template_id):
    require_permission(can_view_settings(request.user))
    template = get_object_or_404(
        DOCXTemplate.objects.select_related("form", "uploaded_by"), pk=template_id
    )
    if request.method == "POST":
        require_permission(can_manage_settings(request.user))
        form = DOCXTemplateStatusForm(request.POST, instance=template)
        if form.is_valid():
            template = form.save(commit=False)
            template.updated_by = request.user
            template.save()
            if template.is_default and template.status == DOCXTemplate.TemplateStatus.ACTIVE:
                template.activate(user=request.user)
            messages.success(request, "DOCX-Vorlage wurde aktualisiert.")
            return redirect("form_builder:docx_template_detail", template_id=template.pk)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        form = DOCXTemplateStatusForm(instance=template)
    return render(
        request,
        "form_builder/docx_templates/detail.html",
        build_app_context(
            request,
            title="DOCX-Vorlage",
            current_url_name="form_builder:docx_template_list",
            template=template,
            template_form=form,
            can_manage_settings=can_manage_settings(request.user),
        ),
    )


@login_required(login_url="login")
def docx_template_file_view(request, template_id):
    require_permission(can_view_settings(request.user))
    template = get_object_or_404(DOCXTemplate, pk=template_id)
    return FileResponse(
        template.template_file.open("rb"),
        as_attachment=True,
        filename=template.original_filename or "template.docx",
        content_type=template.content_type,
    )


@login_required(login_url="login")
def entry_docx_generate_view(request, entry_id):
    form_entry = get_object_or_404(
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by"),
        pk=entry_id,
    )
    if not can_view_entry(request.user, form_entry) or not can_send_entry(request.user, form_entry):
        raise PermissionDenied
    if request.method != "POST":
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    template_id = request.POST.get("template_id")
    template = None
    if template_id:
        template = get_object_or_404(DOCXTemplate, pk=template_id, form=form_entry.form)
    try:
        document = generate_docx_document(
            form_entry=form_entry, template=template, user=request.user
        )
    except ValidationError as exc:
        messages.error(request, exc.message if hasattr(exc, "message") else exc)
        return redirect("form_builder:entry_detail", entry_id=form_entry.pk)
    messages.success(request, "DOCX-Dokument wurde erzeugt.")
    return redirect("form_builder:docx_document_download", document_id=document.pk)


@login_required(login_url="login")
def docx_document_download_view(request, document_id):
    from .models import PDFDocument
    from .permissions import can_view_pdf_document

    document = get_object_or_404(
        PDFDocument.objects.select_related("form_entry", "form", "bewohner"), pk=document_id
    )
    if (
        document.content_type
        != "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        raise PermissionDenied
    if not can_view_pdf_document(request.user, document):
        raise PermissionDenied
    path = get_pdf_private_path(document)
    return FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=document.original_filename,
        content_type=document.content_type,
    )
