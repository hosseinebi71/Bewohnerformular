from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError

from .attachment_models import FormEntryAttachment, detect_content_type, validate_uploaded_file
from .models import AuditLog, Form, FormEntry
from .repeatable_models import RepeatableGroup, RepeatableGroupColumn

_PATCHED = False


def get_repeatable_group_schema(form_definition: Form) -> list[dict]:
    return [
        group.as_builder_dict()
        for group in RepeatableGroup.objects.filter(form=form_definition, is_active=True)
        .prefetch_related("columns")
        .order_by("position", "title")
    ]


def get_augmented_form_schema(form_definition: Form) -> dict:
    schema = deepcopy(form_definition.schema or {})
    if not schema.get("fields") and hasattr(form_definition, "build_schema"):
        schema = form_definition.build_schema()
    schema["repeatable_groups"] = get_repeatable_group_schema(form_definition)
    return schema


def repeatable_groups_for_schema(schema: dict, entry_data: dict | None = None) -> list[dict]:
    entry_data = entry_data or {}
    groups = []
    for group in schema.get("repeatable_groups", []):
        item = deepcopy(group)
        rows = entry_data.get(group.get("key"), [])
        item["rows"] = rows if isinstance(rows, list) else []
        groups.append(item)
    return groups


def parse_repeatable_groups_from_post(schema: dict, post_data, files=None) -> dict[str, list[dict]]:
    payload: dict[str, list[dict]] = {}
    errors: dict[str, list[str]] = {}
    for group in schema.get("repeatable_groups", []):
        group_key = group.get("key")
        if not group_key:
            continue
        max_rows = int(group.get("max_rows") or 0)
        min_rows = int(group.get("min_rows") or 0)
        row_count = _posted_row_count(post_data, group_key)
        rows: list[dict] = []
        for index in range(row_count):
            if _row_marked_for_delete(post_data, group_key, index):
                continue
            row = {}
            non_empty = False
            for column in group.get("columns", []):
                column_key = column.get("key")
                if not column_key:
                    continue
                value = _coerce_column_value(post_data, group_key, index, column)
                if column.get("field_type") == RepeatableGroupColumn.ColumnType.FILE:
                    file_key = repeatable_file_input_name(group_key, index, column_key)
                    uploaded_file = files.get(file_key) if files and hasattr(files, "get") else None
                    if uploaded_file:
                        validate_uploaded_file(uploaded_file, field_definition=column)
                        value = {"_uploaded_file_key": file_key, "filename": uploaded_file.name}
                if value not in (None, "", [], False):
                    non_empty = True
                row[column_key] = value
            if non_empty or _row_required(group):
                row_errors = validate_repeatable_row(group, row, len(rows) + 1)
                if row_errors:
                    errors.setdefault(group_key, []).extend(row_errors)
                rows.append(row)
        if len(rows) < min_rows:
            errors.setdefault(group_key, []).append(
                f"{group.get('title', group_key)} braucht mindestens {min_rows} Zeile(n)."
            )
        if max_rows and len(rows) > max_rows:
            errors.setdefault(group_key, []).append(
                f"{group.get('title', group_key)} erlaubt maximal {max_rows} Zeile(n)."
            )
        payload[group_key] = rows
    if errors:
        raise ValidationError(errors)
    return payload


def _posted_row_count(post_data, group_key: str) -> int:
    raw = (
        post_data.get(f"__repeatable_{group_key}_row_count", "0")
        if hasattr(post_data, "get")
        else "0"
    )
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 0


def _row_marked_for_delete(post_data, group_key: str, index: int) -> bool:
    value = (
        post_data.get(f"__repeatable_{group_key}_{index}_delete", "")
        if hasattr(post_data, "get")
        else ""
    )
    return value in {"1", "true", "True", "on"}


def _row_required(group: dict) -> bool:
    return bool(int(group.get("min_rows") or 0) > 0)


def repeatable_input_name(group_key: str, row_index: int, column_key: str) -> str:
    return f"repeatable__{group_key}__{row_index}__{column_key}"


def repeatable_file_input_name(group_key: str, row_index: int, column_key: str) -> str:
    return repeatable_input_name(group_key, row_index, column_key)


def _coerce_column_value(post_data, group_key: str, index: int, column: dict) -> Any:
    name = repeatable_input_name(group_key, index, column.get("key"))
    field_type = column.get("field_type")
    if field_type == RepeatableGroupColumn.ColumnType.BOOLEAN:
        return name in post_data and post_data.get(name) not in ("", "0", "false", "False")
    value = post_data.get(name, "") if hasattr(post_data, "get") else ""
    if field_type == RepeatableGroupColumn.ColumnType.INTEGER and value not in (None, ""):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if field_type == RepeatableGroupColumn.ColumnType.DECIMAL and value not in (None, ""):
        try:
            return str(Decimal(str(value)))
        except Exception:
            return value
    return value


def validate_repeatable_row(group: dict, row: dict, row_number: int) -> list[str]:
    errors: list[str] = []
    for column in group.get("columns", []):
        key = column.get("key")
        label = column.get("label") or key
        value = row.get(key)
        if column.get("required") and value in (None, "", [], False):
            errors.append(f"Zeile {row_number}: {label} ist ein Pflichtfeld.")
            continue
        if value in (None, "", [], False):
            continue
        field_type = column.get("field_type")
        rules = column.get("validation_rules") or {}
        if field_type in {
            RepeatableGroupColumn.ColumnType.INTEGER,
            RepeatableGroupColumn.ColumnType.DECIMAL,
        }:
            try:
                numeric = Decimal(str(value))
            except Exception:
                errors.append(f"Zeile {row_number}: {label} muss eine Zahl sein.")
                continue
            if rules.get("min_value") is not None and numeric < Decimal(str(rules["min_value"])):
                errors.append(f"Zeile {row_number}: {label} ist zu klein.")
            if rules.get("max_value") is not None and numeric > Decimal(str(rules["max_value"])):
                errors.append(f"Zeile {row_number}: {label} ist zu gross.")
        if field_type == RepeatableGroupColumn.ColumnType.SELECT:
            allowed = {str(choice.get("value")) for choice in column.get("choices", [])}
            if str(value) not in allowed:
                errors.append(f"Zeile {row_number}: {label} enthaelt eine ungueltige Auswahl.")
    return errors


def apply_repeatable_payload(
    *, form_entry: FormEntry, post_data, files=None, user=None
) -> FormEntry:
    schema = form_entry.form_snapshot or get_augmented_form_schema(form_entry.form)
    repeatable_payload = parse_repeatable_groups_from_post(schema, post_data, files=files)
    if not repeatable_payload:
        return form_entry
    data = dict(form_entry.data or {})
    for group_key, rows in repeatable_payload.items():
        data[group_key] = rows
    form_entry.data = data
    form_entry.save(update_fields=["data", "updated_at"])
    _persist_repeatable_file_uploads(form_entry=form_entry, schema=schema, files=files, user=user)
    return form_entry


def _persist_repeatable_file_uploads(
    *, form_entry: FormEntry, schema: dict, files=None, user=None
) -> None:
    if not files:
        return
    data = dict(form_entry.data or {})
    changed = False
    for group in schema.get("repeatable_groups", []):
        group_key = group.get("key")
        rows = data.get(group_key, [])
        if not isinstance(rows, list):
            continue
        for row_index, row in enumerate(rows):
            for column in group.get("columns", []):
                if column.get("field_type") != RepeatableGroupColumn.ColumnType.FILE:
                    continue
                col_key = column.get("key")
                file_key = repeatable_file_input_name(group_key, row_index, col_key)
                uploaded_file = files.get(file_key) if hasattr(files, "get") else None
                if not uploaded_file:
                    continue
                attachment = _store_repeatable_file(
                    form_entry=form_entry,
                    group_key=group_key,
                    row_index=row_index,
                    column_key=col_key,
                    uploaded_file=uploaded_file,
                    column=column,
                    user=user,
                )
                row[col_key] = {
                    "type": "repeatable_file",
                    "attachment_id": str(attachment.pk),
                    "filename": attachment.original_filename,
                    "content_type": attachment.content_type,
                    "size": attachment.size,
                    "sha256": attachment.sha256,
                }
                changed = True
    if changed:
        form_entry.data = data
        form_entry.save(update_fields=["data", "updated_at"])


def _store_repeatable_file(
    *, form_entry, group_key, row_index, column_key, uploaded_file, column, user=None
):
    validate_uploaded_file(uploaded_file, field_definition=column)
    sha256 = _sha256(uploaded_file)
    field_key = f"{group_key}__{row_index}__{column_key}"[:80]
    attachment = FormEntryAttachment.objects.create(
        entry=form_entry,
        field=None,
        field_key=field_key,
        kind=FormEntryAttachment.AttachmentKind.FILE,
        original_filename=getattr(uploaded_file, "name", "attachment.bin")[:255],
        file=uploaded_file,
        content_type=detect_content_type(uploaded_file),
        size=int(getattr(uploaded_file, "size", 0) or 0),
        sha256=sha256,
        uploaded_by=user,
        metadata={
            "source": "repeatable_group",
            "group_key": group_key,
            "row_index": row_index,
            "column_key": column_key,
        },
    )
    AuditLog.objects.create(
        actor=user,
        event_type=AuditLog.EventType.CREATED,
        target_model="FormEntryAttachment",
        target_id=attachment.pk,
        bewohner=form_entry.bewohner,
        form=form_entry.form,
        form_entry=form_entry,
        message="Dateianhang in wiederholbarer Tabelle wurde hochgeladen.",
        metadata={"field_key": field_key, "sha256": sha256},
    )
    return attachment


def _sha256(uploaded_file) -> str:
    pos = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    import hashlib

    digest = hashlib.sha256()
    for chunk in (
        uploaded_file.chunks() if hasattr(uploaded_file, "chunks") else [uploaded_file.read()]
    ):
        digest.update(chunk)
    if pos is not None and hasattr(uploaded_file, "seek"):
        uploaded_file.seek(pos)
    return digest.hexdigest()


def repeatable_tables_for_entry(form_entry: FormEntry) -> list[dict]:
    schema = form_entry.form_snapshot or get_augmented_form_schema(form_entry.form)
    return repeatable_groups_for_schema(schema, form_entry.data or {})


def repeatable_value_for_display(value) -> str:
    if isinstance(value, dict):
        return value.get("filename") or value.get("attachment_id") or "Datei"
    if value is True:
        return "Ja"
    if value is False:
        return "Nein"
    if value in (None, ""):
        return "-"
    return str(value)


def install_repeatable_runtime_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    try:
        from . import pdf_services
    except Exception:
        return
    original_build_official_rows = getattr(pdf_services, "build_official_rows", None)
    if original_build_official_rows is None:
        return

    def build_official_rows_with_repeatables(form_entry, *, data_override=None):
        rows = original_build_official_rows(form_entry, data_override=data_override)
        data = (
            data_override if data_override is not None else (getattr(form_entry, "data", {}) or {})
        )
        schema = getattr(form_entry, "form_snapshot", {}) or {}
        for group in schema.get("repeatable_groups", []):
            group_rows = data.get(group.get("key"), [])
            if not group_rows:
                continue
            lines = []
            headers = [
                column.get("label", column.get("key")) for column in group.get("columns", [])
            ]
            lines.append(" | ".join(headers))
            for row in group_rows:
                lines.append(
                    " | ".join(
                        repeatable_value_for_display(row.get(column.get("key")))
                        for column in group.get("columns", [])
                    )
                )
            rows.append(
                {
                    "label": group.get("title", group.get("key")),
                    "value": "\n".join(lines),
                    "key": group.get("key"),
                }
            )
        return rows

    pdf_services.build_official_rows = build_official_rows_with_repeatables
