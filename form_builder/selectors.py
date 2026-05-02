from django.db.models import Count, Q

from .models import AuditLog, Form, FormEntry, OutboxItem, SentFormArchive


def get_available_forms_queryset():
    return Form.objects.filter(status=Form.PublicationStatus.PUBLISHED).order_by("title")


def get_user_drafts_queryset(user):
    return (
        FormEntry.objects.select_related("form", "bewohner", "created_by")
        .filter(
            created_by=user,
            status__in=[FormEntry.EntryStatus.DRAFT, FormEntry.EntryStatus.REJECTED],
        )
        .order_by("-updated_at")
    )


def get_entries_in_review_queryset():
    return (
        FormEntry.objects.select_related("form", "bewohner", "created_by")
        .filter(status=FormEntry.EntryStatus.IN_REVIEW)
        .order_by("-submitted_at", "-updated_at")
    )


def get_outbox_pending_queryset():
    return (
        OutboxItem.objects.select_related("form", "bewohner", "recipient")
        .filter(status=OutboxItem.DeliveryStatus.PENDING)
        .order_by("next_attempt_at", "created_at")
    )


def get_sent_outbox_queryset():
    return (
        OutboxItem.objects.select_related("form", "bewohner", "recipient")
        .filter(status=OutboxItem.DeliveryStatus.SENT)
        .order_by("-sent_at", "-updated_at")
    )


def get_archive_queryset():
    return (
        SentFormArchive.objects.select_related("form", "bewohner", "form_entry", "pdf_document")
        .order_by("-archived_at")
    )


def get_dashboard_counts(user) -> dict:
    return {
        "available_forms": get_available_forms_queryset().count(),
        "drafts": get_user_drafts_queryset(user).count(),
        "in_review": get_entries_in_review_queryset().count(),
        "outbox_pending": get_outbox_pending_queryset().count(),
        "sent": OutboxItem.objects.filter(status=OutboxItem.DeliveryStatus.SENT).count(),
        "archive": SentFormArchive.objects.count(),
    }


def get_frequent_forms(limit: int = 6):
    return (
        get_available_forms_queryset()
        .annotate(entry_count=Count("entries"))
        .order_by("-entry_count", "title")[:limit]
    )


def get_recent_activity(limit: int = 10):
    recent_entries = (
        FormEntry.objects.select_related("form", "bewohner", "updated_by")
        .exclude(status=FormEntry.EntryStatus.DELETED)
        .order_by("-updated_at")[:limit]
    )
    recent_logs = (
        AuditLog.objects.select_related("actor", "form", "bewohner")
        .filter(
            event_type__in=[
                AuditLog.EventType.STATUS_CHANGED,
                AuditLog.EventType.CREATED,
                AuditLog.EventType.UPDATED,
            ]
        )
        .order_by("-occurred_at")[:limit]
    )
    return {
        "entries": recent_entries,
        "logs": recent_logs,
    }
