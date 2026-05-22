from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .permissions import can_create_entries, can_manage_settings, can_view_settings
from .qr_context_forms import QRFormContextForm
from .qr_context_models import QRFormContext
from .qr_context_services import build_qr_open_url, create_entry_from_qr_context, render_qr_png
from .views import build_app_context, require_permission


@login_required(login_url="login")
def qr_context_list_view(request):
    require_permission(can_view_settings(request.user))
    contexts = QRFormContext.objects.select_related("form", "bewohner", "created_by").order_by(
        "-created_at"
    )
    return render(
        request,
        "form_builder/qr/context_list.html",
        build_app_context(
            request,
            title="QR-Codes",
            current_url_name="form_builder:qr_context_list",
            contexts=contexts,
        ),
    )


@login_required(login_url="login")
def qr_context_create_view(request):
    require_permission(can_manage_settings(request.user))
    if request.method == "POST":
        form = QRFormContextForm(request.POST)
        if form.is_valid():
            context = form.save(commit=False)
            context.created_by = request.user
            context.updated_by = request.user
            context.save()
            messages.success(request, "QR-Kontext wurde erstellt.")
            return redirect("form_builder:qr_context_detail", context_id=context.pk)
    else:
        form = QRFormContextForm()
    return render(
        request,
        "form_builder/qr/context_form.html",
        build_app_context(
            request,
            title="QR-Code erstellen",
            current_url_name="form_builder:qr_context_list",
            form=form,
        ),
    )


@login_required(login_url="login")
def qr_context_detail_view(request, context_id):
    require_permission(can_view_settings(request.user))
    context = get_object_or_404(QRFormContext.objects.select_related("form", "bewohner"), pk=context_id)
    open_url = build_qr_open_url(request, context)
    return render(
        request,
        "form_builder/qr/context_detail.html",
        build_app_context(
            request,
            title="QR-Code",
            current_url_name="form_builder:qr_context_list",
            context=context,
            open_url=open_url,
        ),
    )


@login_required(login_url="login")
def qr_context_png_view(request, context_id):
    require_permission(can_view_settings(request.user))
    context = get_object_or_404(QRFormContext, pk=context_id)
    png = render_qr_png(build_qr_open_url(request, context))
    response = HttpResponse(png, content_type="image/png")
    response["Content-Disposition"] = f'inline; filename="qr-{context.pk}.png"'
    return response


@login_required(login_url="login")
def qr_context_deactivate_view(request, context_id):
    require_permission(can_manage_settings(request.user))
    context = get_object_or_404(QRFormContext, pk=context_id)
    if request.method != "POST":
        return redirect("form_builder:qr_context_detail", context_id=context.pk)
    context.is_active = False
    context.updated_by = request.user
    context.save(update_fields=["is_active", "updated_by", "updated_at"])
    messages.success(request, "QR-Code wurde deaktiviert.")
    return redirect("form_builder:qr_context_detail", context_id=context.pk)


@login_required(login_url="login")
def qr_context_open_view(request, token):
    if not can_create_entries(request.user):
        raise PermissionDenied
    context = get_object_or_404(QRFormContext.objects.select_related("form", "bewohner"), token=token)
    entry = create_entry_from_qr_context(context=context, user=request.user)
    messages.success(request, "QR-Kontext wurde geoeffnet. Bitte Angaben pruefen und speichern.")
    return redirect("form_builder:entry_edit", entry_id=entry.pk)
