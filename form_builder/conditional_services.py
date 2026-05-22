from __future__ import annotations

from collections.abc import Mapping

from django import forms

from .attachment_models import FormEntryAttachment
from .conditional_models import ConditionalRule
from .models import Field, Form, FormEntry

EMPTY_VALUES = (None, "", [], (), {})


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _normalize(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value in EMPTY_VALUES:
        return ""
    if isinstance(value, list):
        return [str(item) for item in value]
    return str(value)


def _value_from_mapping(data, key: str):
    if data is None:
        return None
    if hasattr(data, "getlist"):
        values = data.getlist(key)
        if len(values) > 1:
            return values
        if len(values) == 1:
            return values[0]
    if isinstance(data, Mapping) or hasattr(data, "get"):
        return data.get(key)
    return None


def condition_matches(*, source_value, operator: str, expected: str) -> bool:
    normalized = _normalize(source_value)
    if operator == ConditionalRule.Operator.IS_EMPTY:
        return normalized == "" or normalized == []
    if operator == ConditionalRule.Operator.IS_NOT_EMPTY:
        return not (normalized == "" or normalized == [])
    if isinstance(normalized, list):
        contains = str(expected) in normalized
        return contains if operator == ConditionalRule.Operator.EQUALS else not contains
    matches = normalized == str(expected)
    if operator == ConditionalRule.Operator.NOT_EQUALS:
        return not matches
    return matches


def get_conditional_rules(form: Form):
    return (
        ConditionalRule.objects.select_related("source_field", "target_field", "target_section")
        .filter(form=form, is_active=True)
        .order_by("source_field__position", "created_at")
    )


def get_conditional_rules_payload(form: Form) -> list[dict]:
    return [rule.as_runtime_dict() for rule in get_conditional_rules(form)]


def _schema_fields(schema: dict) -> dict[str, dict]:
    return {field.get("key"): field for field in schema.get("fields", []) if field.get("key")}


def _field_keys_for_section(schema: dict, section_id: str) -> list[str]:
    for section in schema.get("sections", []):
        if str(section.get("id")) == str(section_id):
            return list(section.get("field_keys") or [])
    return []


def _has_active_attachment(form_entry: FormEntry | None, field_key: str) -> bool:
    if not form_entry or not form_entry.pk:
        return False
    return FormEntryAttachment.objects.filter(
        entry=form_entry,
        field_key=field_key,
        deleted_at__isnull=True,
    ).exists()


def _has_uploaded_file(uploaded_files, field_key: str) -> bool:
    if not uploaded_files:
        return False
    if hasattr(uploaded_files, "get"):
        return uploaded_files.get(field_key) is not None
    return False


def _field_has_value(*, field_definition: dict, cleaned_data: dict, uploaded_files=None, form_entry=None) -> bool:
    key = field_definition.get("key")
    if not key:
        return False
    if field_definition.get("field_type") == Field.FieldType.FILE:
        return _has_uploaded_file(uploaded_files, key) or _has_active_attachment(form_entry, key)
    value = cleaned_data.get(key)
    if isinstance(value, str):
        return bool(value.strip())
    return value not in EMPTY_VALUES


def apply_conditional_rules_to_form(
    *,
    form: forms.Form,
    form_definition: Form,
    schema: dict,
    cleaned_data: dict,
    uploaded_files=None,
    form_entry: FormEntry | None = None,
) -> bool:
    """Enforce conditional rules after normal Django validation.

    UX JavaScript may hide/show fields, but this function is the authoritative
    server-side gate. It currently enforces `require` rules and treats show/hide
    as presentation rules. Static `required=True` fields still remain required;
    admins should use `require` rules for conditional requirements.
    """
    fields_by_key = _schema_fields(schema)
    valid = True
    for rule in get_conditional_rules(form_definition):
        source_value = cleaned_data.get(rule.source_field.key)
        if not condition_matches(
            source_value=source_value,
            operator=rule.operator,
            expected=rule.value,
        ):
            continue
        if rule.action != ConditionalRule.Action.REQUIRE:
            continue
        target_keys = []
        if rule.target_field_id:
            target_keys = [rule.target_field.key]
        elif rule.target_section_id:
            target_keys = _field_keys_for_section(schema, str(rule.target_section_id))
        for target_key in target_keys:
            field_definition = fields_by_key.get(target_key)
            if not field_definition:
                continue
            if _field_has_value(
                field_definition=field_definition,
                cleaned_data=cleaned_data,
                uploaded_files=uploaded_files,
                form_entry=form_entry,
            ):
                continue
            message = rule.message or "Dieses Feld ist aufgrund Ihrer Angaben erforderlich."
            if target_key in form.fields:
                form.add_error(target_key, message)
            else:
                form.add_error(None, f"{field_definition.get('label', target_key)}: {message}")
            valid = False
    return valid


def sync_conditional_rule_schema(form: Form) -> None:
    """Store active rule payload in form.schema for rendering/debugging.

    Runtime still reads the database, but embedding a copy in schema makes the
    published structure self-describing and helps future PDF/export work.
    """
    schema = dict(form.schema or form.build_schema())
    schema["conditional_rules"] = get_conditional_rules_payload(form)
    form.schema = schema
    form.save(update_fields=["schema", "updated_at"])
