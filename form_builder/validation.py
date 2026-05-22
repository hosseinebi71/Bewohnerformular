from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from .models import Field


"""
Developer note: field validation_rules format
============================================

validation_rules is a JSON object stored on Field and copied into Form.schema /
FormEntry.form_snapshot. The server-side DynamicEntryForm consumes these rules;
frontend validation is only optional UX sugar.

Supported keys:
- min_value / max_value: numeric bounds for integer and decimal fields. The aliases
  min and max are accepted for import compatibility.
- min_length / max_length: text length bounds for text, textarea, phone, email and
  signature-backed text fields.
- regex / pattern: regular expression for text-like fields.
- regex_message / pattern_message: optional user-facing error for regex failures.
- max_digits / decimal_places: decimal field precision.

Choice fields are validated against Field.choices by Django's ChoiceField /
MultipleChoiceField. Required fields continue to use Field.required so older entries
and older schemas remain compatible.
"""

TEXT_LIKE_FIELD_TYPES = {
    Field.FieldType.TEXT,
    Field.FieldType.TEXTAREA,
    Field.FieldType.EMAIL,
    Field.FieldType.PHONE,
}
NUMERIC_FIELD_TYPES = {Field.FieldType.INTEGER, Field.FieldType.DECIMAL}
ALLOWED_VALIDATION_RULE_KEYS = {
    "min",
    "max",
    "min_value",
    "max_value",
    "min_length",
    "max_length",
    "regex",
    "pattern",
    "regex_message",
    "pattern_message",
    "max_digits",
    "decimal_places",
}


def normalize_validation_rules(rules: dict | None) -> dict:
    if not isinstance(rules, dict):
        return {}
    normalized = dict(rules)
    if "min_value" not in normalized and "min" in normalized:
        normalized["min_value"] = normalized["min"]
    if "max_value" not in normalized and "max" in normalized:
        normalized["max_value"] = normalized["max"]
    if "regex" not in normalized and "pattern" in normalized:
        normalized["regex"] = normalized["pattern"]
    if "regex_message" not in normalized and "pattern_message" in normalized:
        normalized["regex_message"] = normalized["pattern_message"]
    return normalized


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _to_int(value: Any, *, rule_name: str) -> int | None:
    if _blank(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {"validation_rules": f"{rule_name} muss eine Ganzzahl sein."}
        ) from exc


def _to_decimal(value: Any, *, rule_name: str) -> Decimal | None:
    if _blank(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(
            {"validation_rules": f"{rule_name} muss eine Zahl sein."}
        ) from exc


def _validate_no_unknown_rules(rules: dict) -> None:
    unknown = sorted(set(rules) - ALLOWED_VALIDATION_RULE_KEYS)
    if unknown:
        raise ValidationError(
            {
                "validation_rules": (
                    "Unbekannte Validierungsregel(n): " + ", ".join(unknown)
                )
            }
        )


def validate_field_validation_rules(field: Field) -> None:
    """Validate the reusable JSON validation configuration of a Field instance."""
    rules = normalize_validation_rules(field.validation_rules)
    _validate_no_unknown_rules(rules)

    min_length = _to_int(rules.get("min_length"), rule_name="min_length")
    max_length = _to_int(rules.get("max_length"), rule_name="max_length")
    if min_length is not None and min_length < 0:
        raise ValidationError({"validation_rules": "min_length darf nicht negativ sein."})
    if max_length is not None and max_length < 1:
        raise ValidationError({"validation_rules": "max_length muss groesser als 0 sein."})
    if min_length is not None and max_length is not None and min_length > max_length:
        raise ValidationError(
            {"validation_rules": "min_length darf nicht groesser als max_length sein."}
        )

    min_value = _to_decimal(rules.get("min_value"), rule_name="min_value")
    max_value = _to_decimal(rules.get("max_value"), rule_name="max_value")
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValidationError(
            {"validation_rules": "min_value darf nicht groesser als max_value sein."}
        )

    max_digits = _to_int(rules.get("max_digits"), rule_name="max_digits")
    decimal_places = _to_int(rules.get("decimal_places"), rule_name="decimal_places")
    if max_digits is not None and max_digits < 1:
        raise ValidationError({"validation_rules": "max_digits muss groesser als 0 sein."})
    if decimal_places is not None and decimal_places < 0:
        raise ValidationError({"validation_rules": "decimal_places darf nicht negativ sein."})
    if (
        max_digits is not None
        and decimal_places is not None
        and decimal_places > max_digits
    ):
        raise ValidationError(
            {"validation_rules": "decimal_places darf nicht groesser als max_digits sein."}
        )

    regex = rules.get("regex")
    if regex:
        if field.field_type not in TEXT_LIKE_FIELD_TYPES:
            raise ValidationError(
                {"validation_rules": "regex ist nur fuer Textfelder erlaubt."}
            )
        try:
            re.compile(str(regex))
        except re.error as exc:
            raise ValidationError(
                {"validation_rules": f"Ungueltiger regulaerer Ausdruck: {exc}"}
            ) from exc

    if (min_length is not None or max_length is not None) and field.field_type not in TEXT_LIKE_FIELD_TYPES:
        raise ValidationError(
            {"validation_rules": "Laengenregeln sind nur fuer Textfelder erlaubt."}
        )
    if (min_value is not None or max_value is not None) and field.field_type not in NUMERIC_FIELD_TYPES:
        raise ValidationError(
            {"validation_rules": "Wertbereiche sind nur fuer Zahlenfelder erlaubt."}
        )


def get_numeric_bounds(rules: dict | None) -> dict:
    normalized = normalize_validation_rules(rules)
    return {
        "min_value": normalized.get("min_value"),
        "max_value": normalized.get("max_value"),
    }


def get_text_constraints(rules: dict | None) -> dict:
    normalized = normalize_validation_rules(rules)
    constraints = {}
    if normalized.get("min_length") not in (None, ""):
        constraints["min_length"] = int(normalized["min_length"])
    if normalized.get("max_length") not in (None, ""):
        constraints["max_length"] = int(normalized["max_length"])
    return constraints


def get_regex_validators(rules: dict | None) -> list[RegexValidator]:
    normalized = normalize_validation_rules(rules)
    regex = normalized.get("regex")
    if not regex:
        return []
    message = normalized.get("regex_message") or "Bitte das vorgegebene Format einhalten."
    return [RegexValidator(regex=str(regex), message=str(message))]


def normalize_choices(choices: Iterable[dict]) -> list[tuple[str, str]]:
    normalized = []
    for choice in choices or []:
        if not isinstance(choice, dict):
            continue
        value = choice.get("value")
        label = choice.get("label", value)
        if value is None:
            continue
        normalized.append((str(value), str(label)))
    return normalized
