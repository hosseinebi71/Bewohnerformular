from __future__ import annotations

import secrets

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .models import Bewohner, Form, TimeStampedModel, UserStampedModel, UUIDPrimaryKeyModel


def generate_qr_token() -> str:
    return secrets.token_urlsafe(24)


class QRFormContext(UUIDPrimaryKeyModel, TimeStampedModel, UserStampedModel):
    """Opaque QR token that opens a form with optional resident/location context."""

    form = models.ForeignKey(Form, on_delete=models.PROTECT, related_name="qr_contexts")
    bewohner = models.ForeignKey(
        Bewohner,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="qr_contexts",
    )
    label = models.CharField(max_length=255)
    token = models.CharField(max_length=80, unique=True, default=generate_qr_token, db_index=True)
    context_type = models.CharField(
        max_length=40,
        blank=True,
        help_text="Optionaler Kontexttyp, z. B. room, location, asset oder resident.",
    )
    context_key = models.SlugField(
        max_length=120,
        blank=True,
        help_text="Stabiler nicht sensibler Kontextschluessel, z. B. kueche-1 oder raum-a-12.",
    )
    context_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Nicht sensible Vorbelegungen fuer Formularfelder.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["form", "is_active"]),
            models.Index(fields=["expires_at", "is_active"]),
            models.Index(fields=["context_type", "context_key"]),
        ]
        verbose_name = "QR-Formularkontext"
        verbose_name_plural = "QR-Formularkontexte"

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def can_open(self) -> bool:
        return bool(self.is_active and not self.is_expired)

    def clean(self) -> None:
        errors = {}
        if self.form_id and self.form.status != Form.PublicationStatus.PUBLISHED:
            errors["form"] = "QR-Codes duerfen nur auf veroeffentlichte Formulare zeigen."
        if self.bewohner_id and self.context_type and self.context_type not in {"resident", "room"}:
            errors["context_type"] = "Bewohnerbezug ist nur fuer resident/room-Kontexte vorgesehen."
        if self.expires_at and self.expires_at <= timezone.now():
            errors["expires_at"] = "Ablaufdatum muss in der Zukunft liegen."
        if not isinstance(self.context_payload, dict):
            errors["context_payload"] = "Kontextdaten muessen als Objekt gespeichert werden."
        if self.context_key:
            normalized = slugify(self.context_key)[:120]
            if normalized != self.context_key:
                errors["context_key"] = "Kontextschluessel muss ein stabiler Slug sein."
        if errors:
            raise ValidationError(errors)

    def mark_used(self) -> None:
        self.usage_count = (self.usage_count or 0) + 1
        self.last_used_at = timezone.now()
        QRFormContext.objects.filter(pk=self.pk).update(
            usage_count=self.usage_count,
            last_used_at=self.last_used_at,
            updated_at=timezone.now(),
        )

    def __str__(self) -> str:
        return f"{self.label} -> {self.form.key}"
