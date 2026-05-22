from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .conditional_forms import ConditionalRuleForm
from .conditional_models import ConditionalRule
from .conditional_services import sync_conditional_rule_schema
from .models import Form
from .permissions import can_manage_settings
from .views import build_app_context, require_permission


def _require_draft_form(form_definition: Form) -> None:
    if form_definition.status == Form.PublicationStatus.PUBLISHED:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied("Veroeffentlichte Formulare sind im Builder schreibgeschuetzt.")


@login_required(login_url="login")
def conditional_rule_list_view(request, form_id):
    require_permission(can_manage_settings(request.user))
    form_definition = get_object_or_404(Form, pk=form_id)
    rules = form_definition.conditional_rules.select_related(
        "source_field", "target_field", "target_section"
    ).order_by("source_field__position", "created_at")
    return render(
        request,
        "form_builder/settings/conditional_rule_list.html",
        build_app_context(
            request,
            title="Bedingte Regeln",
            current_url_name="form_builder:form_builder_list",
            form_definition=form_definition,
            rules=rules,
            is_locked=form_definition.status == Form.PublicationStatus.PUBLISHED,
        ),
    )


@login_required(login_url="login")
def conditional_rule_create_view(request, form_id):
    require_permission(can_manage_settings(request.user))
    form_definition = get_object_or_404(Form, pk=form_id)
    _require_draft_form(form_definition)
    if request.method == "POST":
        rule_form = ConditionalRuleForm(request.POST, form_definition=form_definition)
        if rule_form.is_valid():
            rule = rule_form.save(commit=False)
            rule.created_by = request.user
            rule.updated_by = request.user
            rule.save()
            sync_conditional_rule_schema(form_definition)
            messages.success(request, "Bedingte Regel wurde gespeichert.")
            return redirect("form_builder:conditional_rule_list", form_id=form_definition.pk)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        rule_form = ConditionalRuleForm(
            form_definition=form_definition, initial={"is_active": True}
        )
    return render(
        request,
        "form_builder/settings/conditional_rule_form.html",
        build_app_context(
            request,
            title="Bedingte Regel anlegen",
            current_url_name="form_builder:form_builder_list",
            form_definition=form_definition,
            rule_form=rule_form,
            mode="create",
        ),
    )


@login_required(login_url="login")
def conditional_rule_edit_view(request, rule_id):
    require_permission(can_manage_settings(request.user))
    rule = get_object_or_404(
        ConditionalRule.objects.select_related(
            "form", "source_field", "target_field", "target_section"
        ),
        pk=rule_id,
    )
    form_definition = rule.form
    _require_draft_form(form_definition)
    if request.method == "POST":
        rule_form = ConditionalRuleForm(
            request.POST,
            form_definition=form_definition,
            instance=rule,
        )
        if rule_form.is_valid():
            rule = rule_form.save(commit=False)
            rule.updated_by = request.user
            rule.save()
            sync_conditional_rule_schema(form_definition)
            messages.success(request, "Bedingte Regel wurde aktualisiert.")
            return redirect("form_builder:conditional_rule_list", form_id=form_definition.pk)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        rule_form = ConditionalRuleForm(form_definition=form_definition, instance=rule)
    return render(
        request,
        "form_builder/settings/conditional_rule_form.html",
        build_app_context(
            request,
            title="Bedingte Regel bearbeiten",
            current_url_name="form_builder:form_builder_list",
            form_definition=form_definition,
            rule=rule,
            rule_form=rule_form,
            mode="edit",
        ),
    )


@login_required(login_url="login")
def conditional_rule_delete_view(request, rule_id):
    require_permission(can_manage_settings(request.user))
    rule = get_object_or_404(ConditionalRule.objects.select_related("form"), pk=rule_id)
    form_definition = rule.form
    _require_draft_form(form_definition)
    if request.method == "POST":
        rule.delete()
        sync_conditional_rule_schema(form_definition)
        messages.success(request, "Bedingte Regel wurde geloescht.")
    return redirect("form_builder:conditional_rule_list", form_id=form_definition.pk)
