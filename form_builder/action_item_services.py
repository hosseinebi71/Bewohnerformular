from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .action_item_models import ActionItem, ActionItemReminderLog, ActionItemRule
from .models import AuditLog, Field, FormEntry

CLOSED_ACTION_STATUSES = {
    ActionItem.Status.DONE,
    ActionItem.Status.VERIFIED,
    ActionItem.Status.CANCELLED,
}
DEFAULT_REVIEW_OVERDUE_DAYS = 2
DEFAULT_DUE_SOON_DAYS = 2
DEFAULT_ESCALATE_AFTER_DAYS = 3


@dataclass(frozen=True)
class ActionItemSyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0

    def summary_de(self) -> str:
        return f"{self.created} Massnahmen erstellt, {self.updated} aktualisiert, {self.skipped} uebersprungen."


@dataclass(frozen=True)
class ReminderProcessingResult:
    action_due_soon: int = 0
    action_overdue: int = 0
    action_escalated: int = 0
    review_overdue: int = 0

    @property
    def total(self) -> int:
        return (
            self.action_due_soon + self.action_overdue + self.action_escalated + self.review_overdue
        )

    def summary_de(self) -> str:
        return (
            f"{self.total} Erinnerung(en): {self.action_due_soon} bald faellig, "
            f"{self.action_overdue} ueberfaellig, {self.action_escalated} eskaliert, "
            f"{self.review_overdue} Review ueberfaellig."
        )


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "ja", "j", "x", "ok", "nicht ok", "nicht_ok"}


def _matches(value: Any, *, operator: str, expected: str = "") -> bool:
    if operator == ActionItemRule.Operator.IS_EMPTY:
        return _is_empty(value)
    if operator == ActionItemRule.Operator.IS_NOT_EMPTY:
        return not _is_empty(value)
    if operator == ActionItemRule.Operator.BOOLEAN_TRUE:
        return _to_bool(value)
    if operator == ActionItemRule.Operator.BOOLEAN_FALSE:
        return not _to_bool(value)
    left = "" if value is None else str(value).strip()
    right = str(expected).strip()
    if operator == ActionItemRule.Operator.EQUALS:
        return left.lower() == right.lower()
    if operator == ActionItemRule.Operator.NOT_EQUALS:
        return left.lower() != right.lower()
    if operator == ActionItemRule.Operator.CONTAINS:
        return right.lower() in left.lower()
    return False


def _safe_format(template: str, context: dict) -> str:
    if not template:
        return ""
    safe = {key: "" if value is None else value for key, value in context.items()}
    try:
        return template.format(**safe)
    except Exception:
        return template


def _parse_due_at(value: Any):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    parsed_datetime = parse_datetime(str(value))
    if parsed_datetime:
        return (
            parsed_datetime
            if timezone.is_aware(parsed_datetime)
            else timezone.make_aware(parsed_datetime)
        )
    parsed_date = parse_date(str(value))
    if parsed_date:
        # Store date-only deadlines around noon in the active timezone.
        # Midnight deadlines shift to the previous UTC day in Europe/Berlin,
        # which makes date-based reporting and tests confusing.
        return timezone.make_aware(
            datetime.combine(parsed_date, time(hour=12, minute=0)),
            timezone.get_current_timezone(),
        )
    return None


def _field_model_for_entry(form_entry: FormEntry, field_key: str):
    return Field.objects.filter(form=form_entry.form, key=field_key).first()


def _audit_action_item(
    *, actor, item: ActionItem, event_type: str, message: str, metadata=None
) -> None:
    AuditLog.objects.create(
        actor=actor,
        event_type=event_type,
        target_model="ActionItem",
        target_id=item.pk,
        bewohner=item.source_entry.bewohner,
        form=item.source_entry.form,
        form_entry=item.source_entry,
        message=message,
        metadata=metadata or {},
    )


def _rule_queryset_for_entry(form_entry: FormEntry):
    return ActionItemRule.objects.filter(form=form_entry.form, is_active=True).select_related(
        "source_field", "assigned_to"
    )


def _simple_rule_context(form_entry: FormEntry, rule: ActionItemRule, value: Any) -> dict:
    data = form_entry.data or {}
    field_key = rule.source_key
    return {
        "form": form_entry.form.title,
        "form_key": form_entry.form.key,
        "entry_id": str(form_entry.pk),
        "field": field_key,
        "field_value": value,
        "value": value,
        "bewohner": str(form_entry.bewohner),
        "massnahme": data.get("massnahme", ""),
        "beschreibung": data.get("beschreibung", data.get("mangel_beschreibung", "")),
        "verantwortlich": data.get("verantwortlich", ""),
        "frist": data.get("frist", ""),
    }


def _row_context(
    form_entry: FormEntry, rule: ActionItemRule, row: dict, row_index: int, value: Any
) -> dict:
    return {
        "form": form_entry.form.title,
        "form_key": form_entry.form.key,
        "entry_id": str(form_entry.pk),
        "group": rule.source_group_key,
        "row": row_index + 1,
        "column": rule.source_column_key,
        "field_value": value,
        "value": value,
        "bewohner": str(form_entry.bewohner),
        "bereich": row.get("bereich", ""),
        "kontrollpunkt": row.get("kontrollpunkt", row.get("punkt", "")),
        "massnahme": row.get("massnahme", ""),
        "beschreibung": row.get("bemerkung", row.get("mangel", "")),
        "verantwortlich": row.get("verantwortlich", ""),
        "frist": row.get("frist", ""),
    }


def _upsert_action_item(
    *,
    form_entry: FormEntry,
    rule: ActionItemRule,
    source_field_key: str,
    source_group_key: str = "",
    source_row_key: str = "",
    title: str,
    description: str,
    assigned_to_label: str = "",
    due_at=None,
    user=None,
    metadata: dict | None = None,
) -> tuple[ActionItem, bool, bool]:
    source_rule_key = f"rule:{rule.pk}"
    source_field = (
        _field_model_for_entry(form_entry, source_field_key) if source_field_key else None
    )
    defaults = {
        "source_field": source_field,
        "source_group_key": source_group_key,
        "title": title[:255] or "Massnahme",
        "description": description,
        "assigned_to": rule.assigned_to,
        "assigned_to_label": assigned_to_label[:255],
        "due_at": due_at,
        "priority": rule.priority,
        "status": ActionItem.Status.OPEN,
        "metadata": metadata or {},
        "created_by": user,
        "updated_by": user,
    }
    item, created = ActionItem.objects.get_or_create(
        source_entry=form_entry,
        source_rule_key=source_rule_key,
        source_row_key=source_row_key,
        source_field_key=source_field_key,
        defaults=defaults,
    )
    updated = False
    if not created and item.status not in CLOSED_ACTION_STATUSES:
        changed_fields = []
        for attr in [
            "title",
            "description",
            "assigned_to",
            "assigned_to_label",
            "due_at",
            "priority",
            "metadata",
        ]:
            value = defaults[attr]
            if getattr(item, attr) != value:
                setattr(item, attr, value)
                changed_fields.append(attr)
        if changed_fields:
            item.updated_by = user
            changed_fields.extend(["updated_by", "updated_at"])
            item.save(update_fields=changed_fields)
            updated = True
    if created:
        _audit_action_item(
            actor=user,
            item=item,
            event_type=AuditLog.EventType.CREATED,
            message="Massnahme wurde automatisch aus einem Formularvorgang erstellt.",
            metadata={"rule_id": str(rule.pk), "source": "action_item_rule"},
        )
    elif updated:
        _audit_action_item(
            actor=user,
            item=item,
            event_type=AuditLog.EventType.UPDATED,
            message="Automatisch erzeugte Massnahme wurde synchronisiert.",
            metadata={"rule_id": str(rule.pk), "source": "action_item_rule"},
        )
    return item, created, updated


def sync_action_items_for_entry(*, form_entry: FormEntry, user=None) -> ActionItemSyncResult:
    """Create or update configured ActionItems for one submitted FormEntry.

    The operation is idempotent: source_entry + rule + row + field is unique,
    and closed tasks are never overwritten by later draft saves.
    """
    created = updated = skipped = 0
    data = form_entry.data or {}
    with transaction.atomic():
        for rule in _rule_queryset_for_entry(form_entry):
            if rule.source_group_key:
                rows = data.get(rule.source_group_key) or []
                if not isinstance(rows, list):
                    skipped += 1
                    continue
                for row_index, row in enumerate(rows):
                    if not isinstance(row, dict):
                        skipped += 1
                        continue
                    value = row.get(rule.source_column_key)
                    if not _matches(value, operator=rule.operator, expected=rule.value):
                        continue
                    context = _row_context(form_entry, rule, row, row_index, value)
                    title = _safe_format(rule.title_template, context)
                    description = (
                        _safe_format(rule.description_template, context)
                        or context.get("massnahme")
                        or context.get("beschreibung")
                    )
                    due_at = (
                        _parse_due_at(row.get(rule.due_at_field_key))
                        if rule.due_at_field_key
                        else None
                    )
                    assigned_to_label = str(row.get(rule.assigned_to_field_key, "") or "")
                    _item, was_created, was_updated = _upsert_action_item(
                        form_entry=form_entry,
                        rule=rule,
                        source_group_key=rule.source_group_key,
                        source_row_key=str(row_index),
                        source_field_key=rule.source_column_key,
                        title=title,
                        description=description,
                        assigned_to_label=assigned_to_label,
                        due_at=due_at,
                        user=user,
                        metadata={"row": row, "row_index": row_index, "rule_id": str(rule.pk)},
                    )
                    created += 1 if was_created else 0
                    updated += 1 if was_updated else 0
            else:
                field_key = rule.source_key
                value = data.get(field_key)
                if not _matches(value, operator=rule.operator, expected=rule.value):
                    continue
                context = _simple_rule_context(form_entry, rule, value)
                title = _safe_format(rule.title_template, context)
                description = _safe_format(rule.description_template, context) or context.get(
                    "beschreibung"
                )
                due_at = (
                    _parse_due_at(data.get(rule.due_at_field_key))
                    if rule.due_at_field_key
                    else None
                )
                assigned_to_label = str(data.get(rule.assigned_to_field_key, "") or "")
                _item, was_created, was_updated = _upsert_action_item(
                    form_entry=form_entry,
                    rule=rule,
                    source_field_key=field_key,
                    title=title,
                    description=description,
                    assigned_to_label=assigned_to_label,
                    due_at=due_at,
                    user=user,
                    metadata={"value": value, "rule_id": str(rule.pk)},
                )
                created += 1 if was_created else 0
                updated += 1 if was_updated else 0
    return ActionItemSyncResult(created=created, updated=updated, skipped=skipped)


def create_hygiene_default_rule_if_missing(*, form, user=None) -> ActionItemRule | None:
    """Convenience helper for generated hygiene imports.

    Import-generated hygiene tables usually expose a repeatable group with a
    `nicht_ok` column. This helper creates a practical default rule without
    requiring admins to understand JSON internals.
    """
    schema = form.schema or form.build_schema()
    for group in schema.get("repeatable_groups", []):
        column_keys = {column.get("key") for column in group.get("columns", [])}
        trigger = "nicht_ok" if "nicht_ok" in column_keys else "ok" if "ok" in column_keys else ""
        if not trigger:
            continue
        operator = (
            ActionItemRule.Operator.BOOLEAN_TRUE
            if trigger == "nicht_ok"
            else ActionItemRule.Operator.BOOLEAN_FALSE
        )
        rule, _created = ActionItemRule.objects.get_or_create(
            form=form,
            source_group_key=group.get("key", ""),
            source_column_key=trigger,
            name="Hygiene-Mangel erzeugt Massnahme",
            defaults={
                "operator": operator,
                "title_template": "Hygiene-Massnahme: {bereich} {kontrollpunkt}",
                "description_template": "{massnahme}\n\nBemerkung: {beschreibung}",
                "assigned_to_field_key": "verantwortlich",
                "due_at_field_key": "frist",
                "priority": ActionItem.Priority.HIGH,
                "created_by": user,
                "updated_by": user,
                "config": {"source": "hygiene_import_default"},
            },
        )
        return rule
    return None


def update_action_item_status(*, item: ActionItem, status: str, user, note: str = "") -> ActionItem:
    old_status = item.status
    item.status = status
    if status == ActionItem.Status.DONE:
        item.completed_at = timezone.now()
    elif status == ActionItem.Status.VERIFIED:
        item.verified_by = user
        item.verified_at = timezone.now()
    elif status == ActionItem.Status.CANCELLED:
        item.cancelled_at = timezone.now()
    item.updated_by = user
    item.save()
    _audit_action_item(
        actor=user,
        item=item,
        event_type=AuditLog.EventType.STATUS_CHANGED,
        message="Massnahmenstatus wurde geaendert.",
        metadata={"old_status": old_status, "new_status": item.status, "note": note},
    )
    return item


def _dedupe_period(now, kind: str) -> str:
    if kind == ActionItemReminderLog.ReminderKind.DUE_SOON:
        return now.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


def _create_action_reminder(*, item: ActionItem, kind: str, now, metadata: dict) -> bool:
    dedupe_key = f"action:{item.pk}:{kind}:{_dedupe_period(now, kind)}"
    log, created = ActionItemReminderLog.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={"action_item": item, "kind": kind, "sent_at": now, "metadata": metadata},
    )
    if created:
        _audit_action_item(
            actor=None,
            item=item,
            event_type=AuditLog.EventType.STATUS_CHANGED,
            message=f"Massnahmen-Erinnerung erzeugt: {kind}.",
            metadata={"reminder_log_id": str(log.pk), **metadata},
        )
    return created


def _create_review_reminder(*, entry: FormEntry, kind: str, now, metadata: dict) -> bool:
    dedupe_key = f"review:{entry.pk}:{kind}:{now.strftime('%Y-%m-%d')}"
    log, created = ActionItemReminderLog.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={"form_entry": entry, "kind": kind, "sent_at": now, "metadata": metadata},
    )
    if created:
        AuditLog.objects.create(
            actor=None,
            event_type=AuditLog.EventType.STATUS_CHANGED,
            target_model="FormEntry",
            target_id=entry.pk,
            bewohner=entry.bewohner,
            form=entry.form,
            form_entry=entry,
            message="Review-Erinnerung wurde erzeugt.",
            metadata={"reminder_log_id": str(log.pk), **metadata},
        )
    return created


def process_reminders(
    *,
    due_soon_days: int = DEFAULT_DUE_SOON_DAYS,
    escalate_after_days: int = DEFAULT_ESCALATE_AFTER_DAYS,
) -> ReminderProcessingResult:
    """Generate deduplicated reminder audit events for tasks and pending reviews."""
    now = timezone.now()
    due_soon = overdue = escalated = review_overdue = 0
    open_items = ActionItem.objects.select_related(
        "source_entry", "source_entry__form", "source_entry__bewohner"
    ).filter(status__in=[ActionItem.Status.OPEN, ActionItem.Status.IN_PROGRESS])
    due_soon_limit = now + timedelta(days=due_soon_days)
    for item in open_items.filter(due_at__isnull=False, due_at__gt=now, due_at__lte=due_soon_limit):
        if _create_action_reminder(
            item=item,
            kind=ActionItemReminderLog.ReminderKind.DUE_SOON,
            now=now,
            metadata={
                "due_at": item.due_at.isoformat(),
                "assigned_to": str(item.assigned_to_id or ""),
            },
        ):
            due_soon += 1
    for item in open_items.filter(due_at__isnull=False, due_at__lte=now):
        if _create_action_reminder(
            item=item,
            kind=ActionItemReminderLog.ReminderKind.OVERDUE,
            now=now,
            metadata={
                "due_at": item.due_at.isoformat(),
                "assigned_to": str(item.assigned_to_id or ""),
            },
        ):
            overdue += 1
        if item.due_at <= now - timedelta(days=escalate_after_days):
            if _create_action_reminder(
                item=item,
                kind=ActionItemReminderLog.ReminderKind.ESCALATION,
                now=now,
                metadata={
                    "due_at": item.due_at.isoformat(),
                    "escalate_after_days": escalate_after_days,
                },
            ):
                escalated += 1
    review_cutoff = now - timedelta(days=DEFAULT_REVIEW_OVERDUE_DAYS)
    for entry in FormEntry.objects.select_related("form", "bewohner").filter(
        status=FormEntry.EntryStatus.IN_REVIEW,
        submitted_at__isnull=False,
        submitted_at__lte=review_cutoff,
    ):
        if _create_review_reminder(
            entry=entry,
            kind=ActionItemReminderLog.ReminderKind.REVIEW_OVERDUE,
            now=now,
            metadata={"submitted_at": entry.submitted_at.isoformat()},
        ):
            review_overdue += 1
    return ReminderProcessingResult(
        action_due_soon=due_soon,
        action_overdue=overdue,
        action_escalated=escalated,
        review_overdue=review_overdue,
    )


def user_queryset_for_assignment():
    User = get_user_model()
    return User.objects.filter(is_active=True).order_by("username")
