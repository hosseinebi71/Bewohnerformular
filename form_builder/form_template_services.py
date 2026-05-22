from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .audit_services import audit_event
from .models import AuditLog, Field, Form, FormSection
from .form_template_models import FormTemplate


def _slugish(value: str, fallback: str) -> str:
    import re

    text = re.sub(r"[^a-z0-9_-]+", "-", (value or "").lower()).strip("-")
    return text[:80] or fallback


@dataclass(frozen=True)
class TemplateCopyResult:
    form: Form
    sections_created: int
    fields_created: int
    repeatable_groups_created: int
    conditional_rules_created: int
    action_rules_created: int


def normalize_template_definition(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Vorlagendefinition muss ein Objekt sein.")
    definition = dict(payload)
    definition.setdefault("form", {})
    definition.setdefault("sections", [])
    definition.setdefault("fields", [])
    definition.setdefault("repeatable_groups", [])
    definition.setdefault("conditional_rules", [])
    definition.setdefault("action_item_rules", [])
    if not definition["sections"] and not definition["fields"]:
        raise ValidationError("Vorlage braucht mindestens ein Feld oder einen Abschnitt.")
    return definition


def create_template_from_definition(*, key: str, title: str, definition: dict, user=None, **metadata) -> FormTemplate:
    normalized = normalize_template_definition(definition)
    template = FormTemplate.objects.create(
        key=_slugish(key, "formularvorlage"),
        version=metadata.get("version", 1),
        title=title,
        category=metadata.get("category", ""),
        description=metadata.get("description", ""),
        language=metadata.get("language", "de"),
        tags=metadata.get("tags", []),
        status=metadata.get("status", FormTemplate.TemplateStatus.ACTIVE),
        definition=normalized,
        created_by=user,
        updated_by=user,
    )
    audit_event(
        actor=user,
        event_type=AuditLog.EventType.CREATED,
        target_model="FormTemplate",
        target_id=template.pk,
        message="Formularvorlage wurde angelegt.",
        metadata={"template_key": template.key, "version": template.version},
    )
    return template


def _next_form_version(form_key: str) -> int:
    current = Form.objects.filter(key=form_key).aggregate(max_version=Max("version"))["max_version"]
    return int(current or 0) + 1


def _choice_list(raw_choices) -> list[dict]:
    choices = []
    for item in raw_choices or []:
        if isinstance(item, dict):
            value = str(item.get("value", item.get("label", ""))).strip()
            label = str(item.get("label", value)).strip()
        else:
            value = label = str(item).strip()
        if value and label:
            choices.append({"value": value, "label": label})
    return choices


def _field_type(value: str) -> str:
    if value == "number":
        return Field.FieldType.INTEGER
    if value == "checkbox":
        return Field.FieldType.BOOLEAN
    if value == "signature":
        return Field.FieldType.TEXT
    return value or Field.FieldType.TEXT


def copy_template_to_form(
    *, template: FormTemplate, user, form_key: str | None = None, title: str | None = None, org_unit: str = ""
) -> TemplateCopyResult:
    if not template.is_active:
        raise ValidationError("Nur aktive Vorlagen koennen kopiert werden.")
    definition = normalize_template_definition(template.definition or {})
    form_meta = definition.get("form") or {}
    key = _slugish(form_key or form_meta.get("key") or template.key, template.key)
    now = timezone.now()

    with transaction.atomic():
        form = Form.objects.create(
            key=key,
            version=_next_form_version(key),
            title=title or form_meta.get("title") or template.title,
            description=form_meta.get("description") or template.description,
            org_unit=org_unit or form_meta.get("org_unit", ""),
            status=Form.PublicationStatus.DRAFT,
            review_required=bool(form_meta.get("review_required", True)),
            is_archivable=bool(form_meta.get("is_archivable", True)),
            retention_period_days=int(form_meta.get("retention_period_days") or 3650),
            created_by=user,
            updated_by=user,
        )
        sections_by_key: dict[str, FormSection] = {}
        for index, section_data in enumerate(definition.get("sections", []), start=1):
            section_key = section_data.get("key") or f"section-{index}"
            section = FormSection.objects.create(
                form=form,
                title=section_data.get("title") or f"Abschnitt {index}",
                description=section_data.get("description", ""),
                position=int(section_data.get("position") or index),
                is_collapsible=bool(section_data.get("is_collapsible", False)),
                is_active=bool(section_data.get("is_active", True)),
                created_by=user,
                updated_by=user,
            )
            sections_by_key[section_key] = section

        fields_created = 0
        next_position = 1
        fields_payload = []
        for section_data in definition.get("sections", []):
            section_key = section_data.get("key")
            for field_data in section_data.get("fields", []):
                enriched = dict(field_data)
                enriched.setdefault("section_key", section_key)
                fields_payload.append(enriched)
        fields_payload.extend(definition.get("fields", []))

        for field_data in fields_payload:
            kind = field_data.get("field_type") or field_data.get("type") or Field.FieldType.TEXT
            ui_config = dict(field_data.get("ui_config") or {})
            if kind == "signature":
                ui_config["widget"] = "signature"
            Field.objects.create(
                form=form,
                section=sections_by_key.get(field_data.get("section_key")),
                key=_slugish(field_data.get("key"), f"feld-{next_position}"),
                label=field_data.get("label") or field_data.get("key") or f"Feld {next_position}",
                help_text=field_data.get("help_text", ""),
                field_type=_field_type(kind),
                position=int(field_data.get("position") or next_position),
                required=bool(field_data.get("required", False)),
                placeholder=field_data.get("placeholder", ""),
                choices=_choice_list(field_data.get("choices")),
                validation_rules=field_data.get("validation_rules") or {},
                ui_config=ui_config,
                is_active=bool(field_data.get("is_active", True)),
                created_by=user,
                updated_by=user,
            )
            fields_created += 1
            next_position += 1

        repeatable_count = _copy_repeatable_groups(form=form, definition=definition, user=user)
        conditional_count = _copy_conditional_rules(form=form, definition=definition, user=user)
        action_rule_count = _copy_action_item_rules(form=form, definition=definition, user=user)
        form.sync_schema()
        form.schema = dict(form.schema or {})
        form.schema["template_source"] = {
            "template_id": str(template.pk),
            "template_key": template.key,
            "template_version": template.version,
            "copied_at": now.isoformat(),
        }
        form.save(update_fields=["schema", "updated_at"])
        audit_event(
            actor=user,
            event_type=AuditLog.EventType.CREATED,
            target_model="Form",
            target_id=form.pk,
            form=form,
            message="Formular wurde aus Vorlage erstellt.",
            metadata={"template_id": str(template.pk), "template_key": template.key},
        )
    return TemplateCopyResult(
        form=form,
        sections_created=len(sections_by_key),
        fields_created=fields_created,
        repeatable_groups_created=repeatable_count,
        conditional_rules_created=conditional_count,
        action_rules_created=action_rule_count,
    )


def _copy_repeatable_groups(*, form: Form, definition: dict, user) -> int:
    try:
        from .repeatable_models import RepeatableGroup, RepeatableGroupColumn
    except Exception:  # pragma: no cover - optional extension import guard
        return 0
    count = 0
    for group_index, group_data in enumerate(definition.get("repeatable_groups", []), start=1):
        group = RepeatableGroup.objects.create(
            form=form,
            key=_slugish(group_data.get("key"), f"tabelle-{group_index}"),
            title=group_data.get("title") or f"Tabelle {group_index}",
            description=group_data.get("description", ""),
            position=int(group_data.get("position") or group_index),
            min_rows=int(group_data.get("min_rows") or 0),
            max_rows=int(group_data.get("max_rows") or 50),
            is_active=bool(group_data.get("is_active", True)),
            created_by=user,
            updated_by=user,
        )
        for column_index, column_data in enumerate(group_data.get("columns", []), start=1):
            RepeatableGroupColumn.objects.create(
                group=group,
                key=_slugish(column_data.get("key"), f"spalte-{column_index}"),
                label=column_data.get("label") or column_data.get("key") or f"Spalte {column_index}",
                column_type=column_data.get("column_type") or column_data.get("field_type") or "text",
                position=int(column_data.get("position") or column_index),
                required=bool(column_data.get("required", False)),
                choices=_choice_list(column_data.get("choices")),
                help_text=column_data.get("help_text", ""),
                created_by=user,
                updated_by=user,
            )
        count += 1
    return count


def _copy_conditional_rules(*, form: Form, definition: dict, user) -> int:
    try:
        from .conditional_models import ConditionalRule
    except Exception:  # pragma: no cover
        return 0
    fields_by_key = {field.key: field for field in form.fields.all()}
    count = 0
    for rule_data in definition.get("conditional_rules", []):
        source_key = rule_data.get("source_field_key") or rule_data.get("source_key")
        target_key = rule_data.get("target_field_key") or rule_data.get("target_key")
        source_field = fields_by_key.get(source_key)
        target_field = fields_by_key.get(target_key)
        if not source_field or not target_field:
            continue
        ConditionalRule.objects.create(
            form=form,
            source_field=source_field,
            target_field=target_field,
            operator=rule_data.get("operator", ConditionalRule.Operator.EQUALS),
            value=rule_data.get("value", ""),
            action=rule_data.get("action", ConditionalRule.Action.SHOW),
            message=rule_data.get("message", ""),
            is_active=bool(rule_data.get("is_active", True)),
            created_by=user,
            updated_by=user,
        )
        count += 1
    return count

def _copy_action_item_rules(*, form: Form, definition: dict, user) -> int:
    try:
        from .action_item_models import ActionItem, ActionItemRule
    except Exception:  # pragma: no cover
        return 0
    count = 0
    for rule_data in definition.get("action_item_rules", []):
        ActionItemRule.objects.create(
            form=form,
            name=rule_data.get("name") or "Massnahme automatisch erstellen",
            source_field_key=rule_data.get("source_field_key", ""),
            source_group_key=rule_data.get("source_group_key", ""),
            source_column_key=rule_data.get("source_column_key", ""),
            operator=rule_data.get("operator", ActionItemRule.Operator.EQUALS),
            value=rule_data.get("value", ""),
            title_template=rule_data.get("title_template", "Massnahme aus {form}"),
            description_template=rule_data.get("description_template", ""),
            assigned_to_field_key=rule_data.get("assigned_to_field_key", ""),
            due_at_field_key=rule_data.get("due_at_field_key", ""),
            priority=rule_data.get("priority", ActionItem.Priority.NORMAL),
            is_active=bool(rule_data.get("is_active", True)),
            config=rule_data.get("config") or {},
            created_by=user,
            updated_by=user,
        )
        count += 1
    return count
