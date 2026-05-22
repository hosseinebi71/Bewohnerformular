from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from .audit_services import audit_permission_denied
from .form_template_forms import FormTemplateCopyForm, FormTemplateCreateForm
from .form_template_models import FormTemplate
from .form_template_services import copy_template_to_form
from .permissions import can_manage_settings, can_view_settings
from .views import build_app_context, require_permission


def _template_queryset():
    return FormTemplate.objects.select_related("created_by", "updated_by").order_by(
        "category", "title", "-version"
    )


@login_required(login_url="login")
def form_template_list_view(request):
    require_permission(can_view_settings(request.user))
    templates = _template_queryset()
    return render(
        request,
        "form_builder/form_templates/list.html",
        build_app_context(
            request,
            title="Formularvorlagen",
            current_url_name="form_builder:form_template_list",
            templates=templates,
            can_manage_settings=can_manage_settings(request.user),
        ),
    )


@login_required(login_url="login")
def form_template_detail_view(request, template_id):
    require_permission(can_view_settings(request.user))
    template = get_object_or_404(_template_queryset(), pk=template_id)
    copy_form = FormTemplateCopyForm(request.POST or None, template=template)
    if request.method == "POST":
        if not can_manage_settings(request.user):
            audit_permission_denied(
                actor=request.user,
                target_model="FormTemplate",
                target_id=template.pk,
                action="copy_template",
                request=request,
                metadata={"template_id": str(template.pk)},
            )
            raise PermissionDenied
        if copy_form.is_valid():
            result = copy_template_to_form(
                template=template,
                user=request.user,
                form_key=copy_form.cleaned_data["form_key"],
                title=copy_form.cleaned_data["title"],
                org_unit=copy_form.cleaned_data.get("org_unit", ""),
            )
            messages.success(
                request,
                f"Formular '{result.form.title}' wurde als editierbarer Entwurf erstellt.",
            )
            return redirect("form_builder:form_builder_edit", form_id=result.form.pk)
        messages.error(request, "Bitte Eingaben pruefen.")
    return render(
        request,
        "form_builder/form_templates/detail.html",
        build_app_context(
            request,
            title=template.title,
            current_url_name="form_builder:form_template_list",
            template=template,
            copy_form=copy_form,
            can_manage_settings=can_manage_settings(request.user),
        ),
    )


@login_required(login_url="login")
def form_template_create_view(request):
    require_permission(can_manage_settings(request.user))
    if request.method == "POST":
        form = FormTemplateCreateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.created_by = request.user
            template.updated_by = request.user
            template.save()
            messages.success(request, "Formularvorlage wurde gespeichert.")
            return redirect("form_builder:form_template_detail", template_id=template.pk)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        form = FormTemplateCreateForm()
    return render(
        request,
        "form_builder/form_templates/form.html",
        build_app_context(
            request,
            title="Formularvorlage anlegen",
            current_url_name="form_builder:form_template_list",
            template_form=form,
        ),
    )
