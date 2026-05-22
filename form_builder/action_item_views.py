from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from .action_item_forms import ActionItemRuleForm, ActionItemStatusForm
from .action_item_models import ActionItem, ActionItemRule
from .action_item_services import update_action_item_status
from .models import Form
from .permissions import can_manage_settings, can_view_entry, can_view_forms
from .views import build_app_context, require_permission


def _can_view_action_item(user, item: ActionItem) -> bool:
    return can_view_entry(user, item.source_entry)


@login_required(login_url="login")
def action_item_list_view(request):
    require_permission(can_view_forms(request.user))
    # Keep object scope in Python because the existing permission layer centralizes
    # entry access in can_view_entry; lists stay small for operational task queues.
    scoped = [
        item
        for item in ActionItem.objects.select_related(
            "source_entry",
            "source_entry__form",
            "source_entry__bewohner",
            "assigned_to",
        ).order_by("status", "due_at", "-created_at")[:300]
        if _can_view_action_item(request.user, item)
    ]
    status = request.GET.get("status", "")
    if status:
        scoped = [item for item in scoped if item.status == status]
    context = build_app_context(
        request,
        title="Massnahmen",
        current_url_name="form_builder:action_item_list",
        items=scoped,
        selected_status=status,
    )
    return render(request, "form_builder/action_items/list.html", context)


@login_required(login_url="login")
def action_item_detail_view(request, item_id):
    require_permission(can_view_forms(request.user))
    item = get_object_or_404(
        ActionItem.objects.select_related(
            "source_entry",
            "source_entry__form",
            "source_entry__bewohner",
            "assigned_to",
            "created_by",
            "updated_by",
        ),
        pk=item_id,
    )
    if not _can_view_action_item(request.user, item):
        raise PermissionDenied
    status_form = ActionItemStatusForm(instance=item)
    context = build_app_context(
        request,
        title="Massnahme",
        current_url_name="form_builder:action_item_list",
        item=item,
        status_form=status_form,
    )
    return render(request, "form_builder/action_items/detail.html", context)


@login_required(login_url="login")
def action_item_update_view(request, item_id):
    require_permission(can_view_forms(request.user))
    item = get_object_or_404(ActionItem.objects.select_related("source_entry"), pk=item_id)
    if not _can_view_action_item(request.user, item):
        raise PermissionDenied
    if request.method != "POST":
        return redirect("form_builder:action_item_detail", item_id=item.pk)
    form = ActionItemStatusForm(request.POST, instance=item)
    if form.is_valid():
        updated = form.save(commit=False)
        item.assigned_to = updated.assigned_to
        item.due_at = updated.due_at
        item.priority = updated.priority
        update_action_item_status(
            item=item,
            status=updated.status,
            user=request.user,
            note=form.cleaned_data.get("note", ""),
        )
        messages.success(request, "Massnahme wurde aktualisiert.")
    else:
        messages.error(request, "Massnahme konnte nicht aktualisiert werden.")
    return redirect("form_builder:action_item_detail", item_id=item.pk)


@login_required(login_url="login")
def action_rule_list_view(request, form_id):
    require_permission(can_manage_settings(request.user))
    form_definition = get_object_or_404(Form, pk=form_id)
    rules = ActionItemRule.objects.filter(form=form_definition).select_related(
        "source_field", "assigned_to"
    )
    return render(
        request,
        "form_builder/action_items/rule_list.html",
        build_app_context(
            request,
            title="Massnahmen-Regeln",
            current_url_name="form_builder:form_builder_list",
            form_definition=form_definition,
            rules=rules,
        ),
    )


@login_required(login_url="login")
def action_rule_create_view(request, form_id):
    require_permission(can_manage_settings(request.user))
    form_definition = get_object_or_404(Form, pk=form_id)
    if request.method == "POST":
        form = ActionItemRuleForm(request.POST, form_definition=form_definition)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.form = form_definition
            rule.created_by = request.user
            rule.updated_by = request.user
            rule.save()
            messages.success(request, "Massnahmen-Regel wurde gespeichert.")
            return redirect("form_builder:action_rule_list", form_id=form_definition.pk)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        form = ActionItemRuleForm(form_definition=form_definition)
    return render(
        request,
        "form_builder/action_items/rule_form.html",
        build_app_context(
            request,
            title="Massnahmen-Regel",
            current_url_name="form_builder:form_builder_list",
            form_definition=form_definition,
            rule_form=form,
            mode="create",
        ),
    )


@login_required(login_url="login")
def action_rule_edit_view(request, rule_id):
    require_permission(can_manage_settings(request.user))
    rule = get_object_or_404(ActionItemRule.objects.select_related("form"), pk=rule_id)
    if request.method == "POST":
        form = ActionItemRuleForm(request.POST, instance=rule, form_definition=rule.form)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated.save()
            messages.success(request, "Massnahmen-Regel wurde aktualisiert.")
            return redirect("form_builder:action_rule_list", form_id=rule.form_id)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        form = ActionItemRuleForm(instance=rule, form_definition=rule.form)
    return render(
        request,
        "form_builder/action_items/rule_form.html",
        build_app_context(
            request,
            title="Massnahmen-Regel",
            current_url_name="form_builder:form_builder_list",
            form_definition=rule.form,
            rule=rule,
            rule_form=form,
            mode="edit",
        ),
    )


@login_required(login_url="login")
def action_rule_delete_view(request, rule_id):
    require_permission(can_manage_settings(request.user))
    rule = get_object_or_404(ActionItemRule.objects.select_related("form"), pk=rule_id)
    form_id = rule.form_id
    if request.method == "POST":
        rule.delete()
        messages.success(request, "Massnahmen-Regel wurde geloescht.")
        return redirect("form_builder:action_rule_list", form_id=form_id)
    return render(
        request,
        "form_builder/action_items/rule_confirm_delete.html",
        build_app_context(
            request,
            title="Massnahmen-Regel loeschen",
            current_url_name="form_builder:form_builder_list",
            rule=rule,
            form_definition=rule.form,
        ),
    )
