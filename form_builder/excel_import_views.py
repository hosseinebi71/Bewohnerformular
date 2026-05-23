from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .excel_import_forms import ExcelImportUploadForm, ExcelMappingForm
from .excel_import_models import ImportJob
from .excel_import_services import (
    create_import_job_from_upload,
    generate_draft_forms_from_mapping,
    save_mapping,
)
from .navigation import get_navigation_items
from .permissions import can_manage_settings, can_view_import_job, can_view_settings


def _require(condition: bool):
    if not condition:
        raise PermissionDenied


def _context(request, *, title: str, current_url_name: str, **extra):
    return {
        "page_title": title,
        "navigation_items": get_navigation_items(request.user, current_url_name=current_url_name),
        "current_url_name": current_url_name,
        **extra,
    }


@login_required(login_url="login")
def excel_import_list_view(request):
    _require(can_view_settings(request.user))
    jobs_qs = ImportJob.objects.select_related("uploaded_by").order_by("-created_at")[:100]
    jobs = [job for job in jobs_qs if can_view_import_job(request.user, job)]
    return render(
        request,
        "form_builder/excel_import/list.html",
        _context(
            request,
            title="Excel-Importe",
            current_url_name="form_builder:excel_import_list",
            jobs=jobs,
            can_manage_settings=can_manage_settings(request.user),
        ),
    )


@login_required(login_url="login")
def excel_import_upload_view(request):
    _require(can_manage_settings(request.user))
    if request.method == "POST":
        form = ExcelImportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                job = create_import_job_from_upload(
                    uploaded_file=form.cleaned_data["uploaded_file"], user=request.user
                )
            except ValidationError as exc:
                form.add_error("uploaded_file", exc)
            else:
                messages.success(request, "Excel-Datei wurde hochgeladen und analysiert.")
                return redirect("form_builder:excel_import_detail", job_id=job.pk)
        messages.error(request, "Excel-Datei konnte nicht importiert werden.")
    else:
        form = ExcelImportUploadForm()
    return render(
        request,
        "form_builder/excel_import/upload.html",
        _context(
            request,
            title="Excel importieren",
            current_url_name="form_builder:excel_import_list",
            upload_form=form,
        ),
    )


@login_required(login_url="login")
def excel_import_detail_view(request, job_id):
    _require(can_view_settings(request.user))
    job = get_object_or_404(ImportJob.objects.select_related("uploaded_by"), pk=job_id)
    _require(can_view_import_job(request.user, job))
    return render(
        request,
        "form_builder/excel_import/detail.html",
        _context(
            request,
            title="Excel-Import",
            current_url_name="form_builder:excel_import_list",
            import_job=job,
            sheets=job.sheets.order_by("sheet_index"),
            can_manage_settings=can_manage_settings(request.user),
        ),
    )


@login_required(login_url="login")
def excel_import_mapping_view(request, job_id):
    _require(can_manage_settings(request.user))
    job = get_object_or_404(ImportJob, pk=job_id)
    _require(can_view_import_job(request.user, job) and can_manage_settings(request.user))
    if request.method == "POST":
        form = ExcelMappingForm(request.POST, job=job)
        if form.is_valid():
            save_mapping(job=job, mapping=form.cleaned_data["mapping"])
            messages.success(request, "Excel-Mapping wurde gespeichert.")
            return redirect("form_builder:excel_import_detail", job_id=job.pk)
        messages.error(request, "Mapping konnte nicht gespeichert werden.")
    else:
        form = ExcelMappingForm(job=job)
    return render(
        request,
        "form_builder/excel_import/mapping.html",
        _context(
            request,
            title="Excel-Mapping",
            current_url_name="form_builder:excel_import_list",
            import_job=job,
            mapping_form=form,
            sheets=(job.analysis_result or {}).get("sheets", []),
        ),
    )


@login_required(login_url="login")
def excel_import_generate_view(request, job_id):
    _require(can_manage_settings(request.user))
    job = get_object_or_404(ImportJob, pk=job_id)
    _require(can_view_import_job(request.user, job) and can_manage_settings(request.user))
    if request.method != "POST":
        return redirect("form_builder:excel_import_detail", job_id=job.pk)
    try:
        forms = generate_draft_forms_from_mapping(job=job, user=request.user)
    except ValidationError as exc:
        job.status = ImportJob.ImportStatus.FAILED
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message", "updated_at"])
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{len(forms)} Formularentwurf/-entwuerfe wurden erzeugt.")
    return redirect("form_builder:excel_import_detail", job_id=job.pk)
