from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from .models import AuditLog
from .pdf_template_forms import PDFTemplatePlacementForm, PDFTemplateUploadForm
from .pdf_template_models import PDFTemplate, PDFTemplatePlacement
from .pdf_template_services import create_pdf_template_from_upload
from .permissions import (
    can_manage_settings,
    can_manage_template,
    can_view_settings,
    can_view_template,
)
from .views import build_app_context


def _require(condition: bool):
    if not condition:
        raise PermissionDenied


@login_required(login_url="login")
def pdf_template_list_view(request):
    _require(can_view_settings(request.user))
    templates_qs = PDFTemplate.objects.select_related("form", "created_by").order_by(
        "form__title", "-created_at"
    )
    templates = [template for template in templates_qs if can_view_template(request.user, template)]
    return render(
        request,
        "form_builder/pdf_templates/list.html",
        build_app_context(
            request,
            title="PDF-Vorlagen",
            current_url_name="form_builder:pdf_template_list",
            templates=templates,
            can_manage_settings=can_manage_settings(request.user),
        ),
    )


@login_required(login_url="login")
def pdf_template_upload_view(request):
    _require(can_manage_settings(request.user))
    if request.method == "POST":
        form = PDFTemplateUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                template = create_pdf_template_from_upload(
                    form=form.cleaned_data["form"],
                    uploaded_file=form.cleaned_data["file"],
                    name=form.cleaned_data.get("name", ""),
                    user=request.user,
                )
            except ValidationError as exc:
                form.add_error("file", exc)
            else:
                messages.success(request, "PDF-Vorlage wurde hochgeladen.")
                return redirect("form_builder:pdf_template_detail", template_id=template.pk)
        messages.error(request, "PDF-Vorlage konnte nicht hochgeladen werden.")
    else:
        form = PDFTemplateUploadForm()
    return render(
        request,
        "form_builder/pdf_templates/upload.html",
        build_app_context(
            request,
            title="PDF-Vorlage hochladen",
            current_url_name="form_builder:pdf_template_list",
            upload_form=form,
        ),
    )


@login_required(login_url="login")
def pdf_template_detail_view(request, template_id):
    _require(can_view_settings(request.user))
    template = get_object_or_404(PDFTemplate.objects.select_related("form"), pk=template_id)
    _require(can_view_template(request.user, template))
    placements = template.placements.select_related("field").order_by(
        "page_number", "field__position", "field__key"
    )
    return render(
        request,
        "form_builder/pdf_templates/detail.html",
        build_app_context(
            request,
            title="PDF-Vorlage",
            current_url_name="form_builder:pdf_template_list",
            template=template,
            placements=placements,
            can_manage_settings=can_manage_settings(request.user),
        ),
    )


@login_required(login_url="login")
def pdf_template_file_view(request, template_id):
    _require(can_view_settings(request.user))
    template = get_object_or_404(PDFTemplate.objects.select_related("form"), pk=template_id)
    _require(can_view_template(request.user, template))
    try:
        return FileResponse(
            template.file.open("rb"),
            content_type="application/pdf",
            filename=template.original_filename,
        )
    except FileNotFoundError as exc:
        raise Http404("PDF-Vorlage wurde nicht gefunden.") from exc


@login_required(login_url="login")
def pdf_template_activate_view(request, template_id):
    _require(can_manage_settings(request.user))
    template = get_object_or_404(PDFTemplate.objects.select_related("form"), pk=template_id)
    _require(can_manage_template(request.user, template))
    if request.method != "POST":
        return redirect("form_builder:pdf_template_detail", template_id=template.pk)
    PDFTemplate.objects.filter(
        form=template.form, status=PDFTemplate.TemplateStatus.ACTIVE
    ).exclude(pk=template.pk).update(status=PDFTemplate.TemplateStatus.RETIRED, is_active=False)
    template.status = PDFTemplate.TemplateStatus.ACTIVE
    template.is_active = True
    template.updated_by = request.user
    template.save(update_fields=["status", "is_active", "updated_by", "updated_at"])
    AuditLog.objects.create(
        actor=request.user,
        event_type=AuditLog.EventType.STATUS_CHANGED,
        target_model="PDFTemplate",
        target_id=template.pk,
        form=template.form,
        message="PDF-Vorlage wurde aktiviert.",
        metadata={"template_id": str(template.pk)},
    )
    messages.success(request, "PDF-Vorlage wurde aktiviert.")
    return redirect("form_builder:pdf_template_detail", template_id=template.pk)


@login_required(login_url="login")
def pdf_template_placement_create_view(request, template_id):
    _require(can_manage_settings(request.user))
    template = get_object_or_404(PDFTemplate.objects.select_related("form"), pk=template_id)
    _require(can_manage_template(request.user, template))
    if request.method == "POST":
        form = PDFTemplatePlacementForm(request.POST, template=template)
        if form.is_valid():
            placement = form.save(commit=False)
            placement.template = template
            placement.created_by = request.user
            placement.updated_by = request.user
            placement.save()
            messages.success(request, "Feldplatzierung wurde gespeichert.")
            return redirect("form_builder:pdf_template_detail", template_id=template.pk)
        messages.error(request, "Bitte Koordinaten und Feld pruefen.")
    else:
        form = PDFTemplatePlacementForm(template=template)
    return render(
        request,
        "form_builder/pdf_templates/placement_form.html",
        build_app_context(
            request,
            title="PDF-Feld platzieren",
            current_url_name="form_builder:pdf_template_list",
            template=template,
            placement_form=form,
            mode="create",
        ),
    )


@login_required(login_url="login")
def pdf_template_placement_edit_view(request, placement_id):
    _require(can_manage_settings(request.user))
    placement = get_object_or_404(
        PDFTemplatePlacement.objects.select_related("template", "template__form", "field"),
        pk=placement_id,
    )
    template = placement.template
    _require(can_manage_template(request.user, template))
    if request.method == "POST":
        form = PDFTemplatePlacementForm(request.POST, template=template, instance=placement)
        if form.is_valid():
            placement = form.save(commit=False)
            placement.template = template
            placement.updated_by = request.user
            placement.save()
            messages.success(request, "Feldplatzierung wurde aktualisiert.")
            return redirect("form_builder:pdf_template_detail", template_id=template.pk)
        messages.error(request, "Bitte Koordinaten und Feld pruefen.")
    else:
        form = PDFTemplatePlacementForm(template=template, instance=placement)
    return render(
        request,
        "form_builder/pdf_templates/placement_form.html",
        build_app_context(
            request,
            title="PDF-Feldplatzierung bearbeiten",
            current_url_name="form_builder:pdf_template_list",
            template=template,
            placement=placement,
            placement_form=form,
            mode="edit",
        ),
    )


@login_required(login_url="login")
def pdf_template_placement_delete_view(request, placement_id):
    _require(can_manage_settings(request.user))
    placement = get_object_or_404(
        PDFTemplatePlacement.objects.select_related("template"),
        pk=placement_id,
    )
    template = placement.template
    _require(can_manage_template(request.user, template))
    if request.method == "POST":
        placement.delete()
        messages.success(request, "Feldplatzierung wurde geloescht.")
    return redirect("form_builder:pdf_template_detail", template_id=template.pk)
