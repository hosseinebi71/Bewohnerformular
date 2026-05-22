from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ConfirmDeleteForm
from .models import Form
from .permissions import can_manage_settings
from .repeatable_forms import RepeatableColumnBuilderForm, RepeatableGroupBuilderForm
from .repeatable_models import RepeatableGroup, RepeatableGroupColumn
from .views import build_app_context


def _require_builder_editable(form_definition: Form) -> None:
    if form_definition.status == Form.PublicationStatus.PUBLISHED:
        raise PermissionDenied("Veroeffentlichte Formulare sind im Builder schreibgeschuetzt.")


def _sync_form(form_definition: Form) -> None:
    form_definition.sync_schema()


@login_required(login_url="login")
def repeatable_group_create_view(request, form_id):
    if not can_manage_settings(request.user):
        raise PermissionDenied
    form_definition = get_object_or_404(Form, pk=form_id)
    _require_builder_editable(form_definition)
    if request.method == "POST":
        builder_form = RepeatableGroupBuilderForm(request.POST, form_definition=form_definition)
        if builder_form.is_valid():
            group = builder_form.save(commit=False)
            group.created_by = request.user
            group.updated_by = request.user
            group.save()
            _sync_form(form_definition)
            messages.success(request, "Wiederholbare Tabelle wurde gespeichert.")
            return redirect("form_builder:repeatable_group_edit", group_id=group.pk)
        messages.error(request, "Tabelle konnte nicht gespeichert werden. Bitte Eingaben pruefen.")
    else:
        builder_form = RepeatableGroupBuilderForm(form_definition=form_definition)
    context = build_app_context(
        request,
        title="Wiederholbare Tabelle anlegen",
        current_url_name="form_builder:form_builder_list",
        form_definition=form_definition,
        builder_form=builder_form,
        mode="create",
    )
    return render(request, "form_builder/settings/repeatable_group_form.html", context)


@login_required(login_url="login")
def repeatable_group_edit_view(request, group_id):
    if not can_manage_settings(request.user):
        raise PermissionDenied
    group = get_object_or_404(RepeatableGroup.objects.select_related("form", "section"), pk=group_id)
    _require_builder_editable(group.form)
    if request.method == "POST":
        builder_form = RepeatableGroupBuilderForm(request.POST, form_definition=group.form, instance=group)
        if builder_form.is_valid():
            group = builder_form.save(commit=False)
            group.updated_by = request.user
            group.save()
            _sync_form(group.form)
            messages.success(request, "Tabelle wurde aktualisiert.")
            return redirect("form_builder:repeatable_group_edit", group_id=group.pk)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        builder_form = RepeatableGroupBuilderForm(form_definition=group.form, instance=group)
    context = build_app_context(
        request,
        title="Wiederholbare Tabelle bearbeiten",
        current_url_name="form_builder:form_builder_list",
        form_definition=group.form,
        group=group,
        columns=group.columns.all().order_by("position", "key"),
        builder_form=builder_form,
        mode="edit",
    )
    return render(request, "form_builder/settings/repeatable_group_form.html", context)


@login_required(login_url="login")
def repeatable_group_delete_view(request, group_id):
    if not can_manage_settings(request.user):
        raise PermissionDenied
    group = get_object_or_404(RepeatableGroup.objects.select_related("form"), pk=group_id)
    form_definition = group.form
    _require_builder_editable(form_definition)
    if request.method == "POST":
        confirm_form = ConfirmDeleteForm(request.POST)
        if confirm_form.is_valid():
            group.delete()
            _sync_form(form_definition)
            messages.success(request, "Tabelle wurde geloescht.")
    return redirect("form_builder:form_builder_edit", form_definition.pk)


def _swap_position(obj, queryset, direction: str) -> None:
    items = list(queryset)
    index = items.index(obj)
    target_index = index - 1 if direction == "up" else index + 1
    if target_index < 0 or target_index >= len(items):
        return
    target = items[target_index]
    temporary_position = max(item.position for item in items) + 1
    with transaction.atomic():
        obj.__class__.objects.filter(pk=obj.pk).update(position=temporary_position)
        obj.__class__.objects.filter(pk=target.pk).update(position=obj.position)
        obj.__class__.objects.filter(pk=obj.pk).update(position=target.position)


@login_required(login_url="login")
def repeatable_group_reorder_view(request, group_id, direction):
    if not can_manage_settings(request.user):
        raise PermissionDenied
    group = get_object_or_404(RepeatableGroup.objects.select_related("form"), pk=group_id)
    _require_builder_editable(group.form)
    if request.method == "POST" and direction in {"up", "down"}:
        _swap_position(group, RepeatableGroup.objects.filter(form=group.form).order_by("position", "title"), direction)
        _sync_form(group.form)
    return redirect("form_builder:form_builder_edit", group.form_id)


@login_required(login_url="login")
def repeatable_column_create_view(request, group_id):
    if not can_manage_settings(request.user):
        raise PermissionDenied
    group = get_object_or_404(RepeatableGroup.objects.select_related("form"), pk=group_id)
    _require_builder_editable(group.form)
    if request.method == "POST":
        column_form = RepeatableColumnBuilderForm(request.POST, group=group)
        if column_form.is_valid():
            column = column_form.save(commit=False)
            column.created_by = request.user
            column.updated_by = request.user
            column.save()
            _sync_form(group.form)
            messages.success(request, "Spalte wurde gespeichert.")
            return redirect("form_builder:repeatable_group_edit", group_id=group.pk)
        messages.error(request, "Spalte konnte nicht gespeichert werden. Bitte Eingaben pruefen.")
    else:
        column_form = RepeatableColumnBuilderForm(group=group)
    context = build_app_context(
        request,
        title="Tabellenspalte anlegen",
        current_url_name="form_builder:form_builder_list",
        form_definition=group.form,
        group=group,
        column_form=column_form,
        mode="create",
    )
    return render(request, "form_builder/settings/repeatable_column_form.html", context)


@login_required(login_url="login")
def repeatable_column_edit_view(request, column_id):
    if not can_manage_settings(request.user):
        raise PermissionDenied
    column = get_object_or_404(RepeatableGroupColumn.objects.select_related("group", "group__form"), pk=column_id)
    _require_builder_editable(column.group.form)
    if request.method == "POST":
        column_form = RepeatableColumnBuilderForm(request.POST, group=column.group, instance=column)
        if column_form.is_valid():
            column = column_form.save(commit=False)
            column.updated_by = request.user
            column.save()
            _sync_form(column.group.form)
            messages.success(request, "Spalte wurde aktualisiert.")
            return redirect("form_builder:repeatable_group_edit", group_id=column.group_id)
        messages.error(request, "Bitte Eingaben pruefen.")
    else:
        column_form = RepeatableColumnBuilderForm(group=column.group, instance=column)
    context = build_app_context(
        request,
        title="Tabellenspalte bearbeiten",
        current_url_name="form_builder:form_builder_list",
        form_definition=column.group.form,
        group=column.group,
        column=column,
        column_form=column_form,
        mode="edit",
    )
    return render(request, "form_builder/settings/repeatable_column_form.html", context)


@login_required(login_url="login")
def repeatable_column_delete_view(request, column_id):
    if not can_manage_settings(request.user):
        raise PermissionDenied
    column = get_object_or_404(RepeatableGroupColumn.objects.select_related("group", "group__form"), pk=column_id)
    group = column.group
    _require_builder_editable(group.form)
    if request.method == "POST":
        confirm_form = ConfirmDeleteForm(request.POST)
        if confirm_form.is_valid():
            column.delete()
            _sync_form(group.form)
            messages.success(request, "Spalte wurde geloescht.")
    return redirect("form_builder:repeatable_group_edit", group_id=group.pk)


@login_required(login_url="login")
def repeatable_column_reorder_view(request, column_id, direction):
    if not can_manage_settings(request.user):
        raise PermissionDenied
    column = get_object_or_404(RepeatableGroupColumn.objects.select_related("group", "group__form"), pk=column_id)
    _require_builder_editable(column.group.form)
    if request.method == "POST" and direction in {"up", "down"}:
        _swap_position(column, column.group.columns.order_by("position", "key"), direction)
        _sync_form(column.group.form)
    return redirect("form_builder:repeatable_group_edit", group_id=column.group_id)
