from __future__ import annotations

from uuid import UUID, uuid4

from .models import AuditLog


def _target_id(value=None):
    if value:
        return value
    return uuid4()


def audit_event(
    *,
    actor,
    event_type: str,
    target_model: str,
    target_id=None,
    bewohner=None,
    form=None,
    form_entry=None,
    message: str = "",
    metadata: dict | None = None,
    request=None,
) -> AuditLog:
    """Create a structured audit event while preserving the existing hash chain.

    The project already has an append-only AuditLog model with a chained SHA-256
    hash. This helper keeps new audit coverage consistent and avoids ad-hoc log
    rows with inconsistent metadata keys.
    """

    remote_addr = ""
    user_agent = ""
    if request is not None:
        remote_addr = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        if not remote_addr:
            remote_addr = request.META.get("REMOTE_ADDR", "")
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:512]

    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        event_type=event_type,
        target_model=target_model,
        target_id=_target_id(target_id),
        bewohner=bewohner,
        form=form,
        form_entry=form_entry,
        remote_addr=remote_addr or None,
        user_agent=user_agent,
        message=message[:255],
        metadata=metadata or {},
    )


def audit_permission_denied(
    *,
    actor,
    target_model: str,
    target_id=None,
    action: str,
    bewohner=None,
    form=None,
    form_entry=None,
    request=None,
    metadata: dict | None = None,
) -> AuditLog:
    payload = {"action": action, **(metadata or {})}
    return audit_event(
        actor=actor,
        event_type=AuditLog.EventType.PERMISSION_DENIED,
        target_model=target_model,
        target_id=target_id,
        bewohner=bewohner,
        form=form,
        form_entry=form_entry,
        request=request,
        message="Zugriff wurde durch serverseitige Berechtigungspruefung verweigert.",
        metadata=payload,
    )


def audit_download(
    *,
    actor,
    target_model: str,
    target_id,
    bewohner=None,
    form=None,
    form_entry=None,
    request=None,
    metadata: dict | None = None,
) -> AuditLog:
    return audit_event(
        actor=actor,
        event_type=AuditLog.EventType.DOWNLOAD,
        target_model=target_model,
        target_id=target_id,
        bewohner=bewohner,
        form=form,
        form_entry=form_entry,
        request=request,
        message="Dokument oder Export wurde heruntergeladen.",
        metadata=metadata or {},
    )


def audit_export(
    *,
    actor,
    target_model: str = "Export",
    target_id: UUID | None = None,
    form=None,
    request=None,
    metadata: dict | None = None,
) -> AuditLog:
    return audit_event(
        actor=actor,
        event_type=AuditLog.EventType.DOWNLOAD,
        target_model=target_model,
        target_id=target_id,
        form=form,
        request=request,
        message="Datenexport wurde erzeugt.",
        metadata={"action": "export", **(metadata or {})},
    )
