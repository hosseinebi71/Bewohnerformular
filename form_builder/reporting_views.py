from __future__ import annotations

from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .audit_services import audit_export, audit_permission_denied
from .models import Form
from .permissions import can_export_entries, can_view_dashboard, can_view_form, can_view_forms
from .reporting_services import (
    export_entries_to_xlsx,
    get_operational_dashboard_data,
    parse_date_period,
    render_monthly_report_pdf,
    scoped_entries,
)
from .views import build_app_context, require_permission


@login_required(login_url="login")
def operational_dashboard_view(request):
    require_permission(can_view_dashboard(request.user))
    context = build_app_context(
        request,
        title="Betriebsdashboard",
        current_url_name="form_builder:operational_dashboard",
        operational_dashboard=get_operational_dashboard_data(request.user),
    )
    return render(request, "form_builder/reports/operational_dashboard.html", context)


def _require_export_permission(request, *, form=None) -> None:
    if not can_export_entries(request.user):
        audit_permission_denied(
            actor=request.user,
            target_model="Export",
            action="export_entries",
            form=form,
            request=request,
        )
        raise PermissionDenied
    if form is not None and not can_view_form(request.user, form):
        audit_permission_denied(
            actor=request.user,
            target_model="Form",
            target_id=form.pk,
            action="export_form_entries",
            form=form,
            request=request,
        )
        raise PermissionDenied


@login_required(login_url="login")
def entries_excel_export_view(request):
    require_permission(can_view_forms(request.user))
    form = None
    form_id = request.GET.get("form")
    if form_id:
        form = get_object_or_404(Form, pk=form_id)
    _require_export_permission(request, form=form)
    period = None
    if request.GET.get("start") or request.GET.get("end"):
        period = parse_date_period(request.GET.get("start"), request.GET.get("end"))
    entries = scoped_entries(request.user, form=form, period=period)
    entry_count = entries.count()
    if not entry_count:
        messages.info(request, "Keine exportierbaren Eintraege gefunden.")
    workbook = export_entries_to_xlsx(user=request.user, entries=entries)
    audit_export(
        actor=request.user,
        form=form,
        request=request,
        metadata={
            "format": "xlsx",
            "entry_count": entry_count,
            "form_id": str(form.pk) if form else None,
            "start": request.GET.get("start", ""),
            "end": request.GET.get("end", ""),
        },
    )
    filename = f"formulare_export_{timezone.localdate().isoformat()}.xlsx"
    response = HttpResponse(
        workbook,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required(login_url="login")
def monthly_pdf_report_view(request):
    require_permission(can_view_forms(request.user))
    form = None
    form_id = request.GET.get("form")
    if form_id:
        form = get_object_or_404(Form, pk=form_id)
    _require_export_permission(request, form=form)
    period = parse_date_period(request.GET.get("start"), request.GET.get("end"))
    pdf_bytes = render_monthly_report_pdf(user=request.user, form=form, period=period)
    audit_export(
        actor=request.user,
        target_model="MonthlyPDFReport",
        target_id=uuid4(),
        form=form,
        request=request,
        metadata={
            "format": "pdf",
            "form_id": str(form.pk) if form else None,
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
        },
    )
    filename = f"monatsbericht_{timezone.localdate().isoformat()}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
