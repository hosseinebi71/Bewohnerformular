from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Form
from .permissions import can_view_dashboard, can_view_form, can_view_forms
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


@login_required(login_url="login")
def entries_excel_export_view(request):
    require_permission(can_view_forms(request.user))
    form = None
    form_id = request.GET.get("form")
    if form_id:
        form = get_object_or_404(Form, pk=form_id)
        require_permission(can_view_form(request.user, form))
    period = None
    if request.GET.get("start") or request.GET.get("end"):
        period = parse_date_period(request.GET.get("start"), request.GET.get("end"))
    entries = scoped_entries(request.user, form=form, period=period)
    if not entries.exists():
        messages.info(request, "Keine exportierbaren Eintraege gefunden.")
    workbook = export_entries_to_xlsx(user=request.user, entries=entries)
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
        require_permission(can_view_form(request.user, form))
    period = parse_date_period(request.GET.get("start"), request.GET.get("end"))
    pdf_bytes = render_monthly_report_pdf(user=request.user, form=form, period=period)
    filename = f"monatsbericht_{timezone.localdate().isoformat()}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
