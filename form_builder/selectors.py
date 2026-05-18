from django.db.models import Count, Q

from .models import AuditLog, Form, FormEntry, FormSchedule, OutboxItem, SentFormArchive
from .permissions import entry_scope_q, form_scope_q, has_unrestricted_data_scope


def get_available_forms_queryset(user=None):
    queryset = Form.objects.filter(status=Form.PublicationStatus.PUBLISHED)
    if user is not None and not _can_view_all_work_items(user):
        queryset = queryset.filter(form_scope_q(user))
    return queryset.order_by("title")


def _can_view_all_work_items(user) -> bool:
    return has_unrestricted_data_scope(user)


def _related_entry_scope_q(user, *, prefix: str) -> Q:
    q = entry_scope_q(user)
    if not q.children:
        return q

    def rewrite(node):
        if isinstance(node, Q):
            rewritten = Q()
            rewritten.connector = node.connector
            rewritten.negated = node.negated
            rewritten.children = [rewrite(child) for child in node.children]
            return rewritten
        lookup, value = node
        if lookup == "pk__isnull":
            return (prefix + "pk__isnull", value)
        return (prefix + lookup, value)

    return rewrite(q)


def get_user_drafts_queryset(user):
    # Arbeitsliste: offene, noch nicht versendete Eintraege.
    # Admin/Staff sehen die gesamte Arbeitsliste; normale Mitarbeiter nur eigene Eintraege.
    queryset = FormEntry.objects.select_related("form", "bewohner", "created_by").filter(
        status__in=OPEN_DISPATCH_STATUSES
    )
    if user is not None and not _can_view_all_work_items(user):
        queryset = queryset.filter(entry_scope_q(user))
    return queryset.order_by("-updated_at")


def get_entries_in_review_queryset(user=None):
    queryset = (
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by")
        .filter(status=FormEntry.EntryStatus.IN_REVIEW)
        .order_by("-submitted_at", "-updated_at")
    )
    if user is not None and not _can_view_all_work_items(user):
        queryset = queryset.filter(entry_scope_q(user))
    return queryset


def get_outbox_pending_queryset(user=None):
    queryset = (
        OutboxItem.objects.select_related(
            "form",
            "bewohner",
            "recipient",
            "form_entry",
            "form_entry__created_by",
            "form_entry__updated_by",
        )
        .filter(status=OutboxItem.DeliveryStatus.PENDING)
        .order_by("next_attempt_at", "created_at")
    )
    if user is not None and not _can_view_all_work_items(user):
        queryset = queryset.filter(_related_entry_scope_q(user, prefix="form_entry__"))
    return queryset


def get_sent_outbox_queryset(user=None):
    queryset = (
        OutboxItem.objects.select_related(
            "form",
            "bewohner",
            "recipient",
            "form_entry",
            "form_entry__created_by",
            "form_entry__updated_by",
        )
        .filter(status=OutboxItem.DeliveryStatus.SENT)
        .order_by("-sent_at", "-updated_at")
    )
    if user is not None and not _can_view_all_work_items(user):
        queryset = queryset.filter(_related_entry_scope_q(user, prefix="form_entry__"))
    return queryset


def get_archive_queryset(user=None):
    queryset = SentFormArchive.objects.select_related(
        "form",
        "bewohner",
        "form_entry",
        "form_entry__created_by",
        "form_entry__updated_by",
        "pdf_document",
    ).order_by("-archived_at")
    if user is not None and not _can_view_all_work_items(user):
        queryset = queryset.filter(_related_entry_scope_q(user, prefix="form_entry__"))
    return queryset


def get_dashboard_counts(user) -> dict:
    return {
        "available_forms": get_available_forms_queryset(user=user).count(),
        "drafts": get_user_drafts_queryset(user).count(),
        "in_review": get_entries_in_review_queryset(user=user).count(),
        "outbox_pending": get_open_dispatch_entries_queryset(user=user).count(),
        "sent": get_sent_outbox_queryset(user=user).count(),
        "archive": get_archive_queryset(user=user).count(),
    }


def get_frequent_forms(limit: int = 6, user=None):
    return (
        get_available_forms_queryset(user=user)
        .annotate(entry_count=Count("entries"))
        .order_by("-entry_count", "title")[:limit]
    )


def get_recent_activity(limit: int = 10, user=None):
    recent_entries_qs = (
        FormEntry.objects.select_related("form", "bewohner", "created_by", "updated_by")
        .exclude(status=FormEntry.EntryStatus.DELETED)
        .order_by("-updated_at")
    )
    if user is not None and not _can_view_all_work_items(user):
        recent_entries_qs = recent_entries_qs.filter(entry_scope_q(user))
    recent_entries = recent_entries_qs[:limit]
    recent_logs_qs = AuditLog.objects.select_related(
        "actor", "form", "bewohner", "form_entry"
    ).filter(
        event_type__in=[
            AuditLog.EventType.STATUS_CHANGED,
            AuditLog.EventType.CREATED,
            AuditLog.EventType.UPDATED,
        ]
    )
    if user is not None and not _can_view_all_work_items(user):
        recent_logs_qs = recent_logs_qs.filter(_related_entry_scope_q(user, prefix="form_entry__"))
    recent_logs = recent_logs_qs.order_by("-occurred_at")[:limit]
    return {
        "entries": recent_entries,
        "logs": recent_logs,
    }


OPEN_DISPATCH_STATUSES = [
    FormEntry.EntryStatus.DRAFT,
    FormEntry.EntryStatus.REJECTED,
    FormEntry.EntryStatus.APPROVED,
    FormEntry.EntryStatus.READY_TO_SEND,
]


def get_open_dispatch_entries_queryset(user=None):
    """Entries that still belong to the current, unsent working list."""
    queryset = FormEntry.objects.select_related(
        "form", "bewohner", "created_by", "updated_by"
    ).filter(status__in=OPEN_DISPATCH_STATUSES)
    if user is not None and not _can_view_all_work_items(user):
        queryset = queryset.filter(entry_scope_q(user))
    return queryset.order_by("form__title", "created_at")


def _schedule_labels_for_forms(forms) -> dict:
    form_ids = [form.pk for form in forms]
    if not form_ids:
        return {}
    schedules = (
        FormSchedule.objects.filter(form_id__in=form_ids, is_active=True)
        .exclude(status=FormSchedule.ScheduleStatus.RETIRED)
        .order_by("form_id", "next_run_at", "name")
    )
    first_schedule_by_form = {}
    for schedule in schedules:
        first_schedule_by_form.setdefault(schedule.form_id, schedule)

    labels = {}
    for form in forms:
        schedule = first_schedule_by_form.get(form.pk)
        if schedule:
            config = schedule.config or {}
            rhythm = config.get("frequency") or (form.schema or {}).get("dispatch", {}).get(
                "rhythm", "manual"
            )
            if rhythm == "daily":
                label = "Täglich"
            elif rhythm == "weekly":
                label = "Wöchentlich"
            else:
                label = "Manuell"
            next_label = (
                schedule.next_run_at.strftime("%d.%m.%Y %H:%M")
                if schedule.next_run_at
                else schedule.cron_expression or "noch nicht geplant"
            )
            labels[form.pk] = (label, next_label)
            continue

        config = (getattr(form, "schema", {}) or {}).get("dispatch", {})
        rhythm = config.get("rhythm", "manual")
        send_time = config.get("send_time", "")
        weekday = config.get("weekday", "")
        if rhythm == "daily":
            labels[form.pk] = ("Täglich", f"täglich {send_time or '05:00'}")
        elif rhythm == "weekly":
            weekday_label = f"wöchentlich {weekday}".strip()
            labels[form.pk] = ("Wöchentlich", f"{weekday_label} {send_time}".strip())
        else:
            labels[form.pk] = ("Manuell", "manueller Versand")
    return labels


def get_pending_dispatch_groups(user=None):
    """Group unsent entries by form so collecting forms stay together until sent."""
    entries = list(get_open_dispatch_entries_queryset(user=user))
    labels_by_form = _schedule_labels_for_forms([entry.form for entry in entries])
    groups_by_form = {}
    for entry in entries:
        form_id = entry.form_id
        if form_id not in groups_by_form:
            rhythm, next_run = labels_by_form.get(form_id, ("Manuell", "manueller Versand"))
            groups_by_form[form_id] = {
                "form": entry.form,
                "entries": [],
                "count": 0,
                "draft_count": 0,
                "review_count": 0,
                "approved_count": 0,
                "ready_count": 0,
                "rhythm": rhythm,
                "next_run_label": next_run,
                "status_label": "Offene Sammelliste",
            }
        group = groups_by_form[form_id]
        group["entries"].append(entry)
        group["count"] += 1
        if entry.status in [FormEntry.EntryStatus.DRAFT, FormEntry.EntryStatus.REJECTED]:
            group["draft_count"] += 1
        elif entry.status == FormEntry.EntryStatus.IN_REVIEW:
            group["review_count"] += 1
        elif entry.status == FormEntry.EntryStatus.APPROVED:
            group["approved_count"] += 1
        elif entry.status == FormEntry.EntryStatus.READY_TO_SEND:
            group["ready_count"] += 1
    return sorted(groups_by_form.values(), key=lambda item: item["form"].title.lower())
