from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils import timezone

from .models import AuditLog, FormEntry, PDFDocument


PDF_TEMPLATE = "form_builder/pdf/form_entry_pdf.html"


def get_private_document_root() -> Path:
    """Return the private document root used for generated PDFs."""
    return Path(getattr(settings, "PRIVATE_DOCUMENT_ROOT", settings.BASE_DIR / "private_documents"))


def get_entry_detail_rows(form_entry: FormEntry) -> list[dict]:
    rows: list[dict] = []
    schema = form_entry.form_snapshot or {}
    for field_definition in schema.get("fields", []):
        raw_value = form_entry.data.get(field_definition["key"], "-")
        if isinstance(raw_value, list):
            value = ", ".join(str(item) for item in raw_value) or "-"
        elif raw_value in (None, ""):
            value = "-"
        else:
            value = raw_value
        rows.append(
            {
                "label": field_definition.get("label", field_definition.get("key", "Feld")),
                "value": value,
                "field_type": field_definition.get("field_type", "text"),
                "sensitivity": field_definition.get("sensitivity", "normal"),
            }
        )
    return rows


def build_pdf_context(*, form_entry: FormEntry, generated_by=None) -> dict:
    return {
        "form_entry": form_entry,
        "detail_rows": get_entry_detail_rows(form_entry),
        "generated_at": timezone.now(),
        "generated_by": generated_by,
        "company_name": getattr(settings, "PDF_COMPANY_NAME", "Bewohner-Formularsystem"),
    }


def render_entry_pdf_html(*, form_entry: FormEntry, generated_by=None) -> str:
    return render_to_string(PDF_TEMPLATE, build_pdf_context(form_entry=form_entry, generated_by=generated_by))


def get_latest_generated_pdf_document(form_entry: FormEntry) -> PDFDocument | None:
    return (
        PDFDocument.objects.filter(
            form_entry=form_entry,
            document_kind__in=[PDFDocument.DocumentKind.REVIEW, PDFDocument.DocumentKind.FINAL],
            status=PDFDocument.GenerationStatus.GENERATED,
        )
        .order_by("-generated_at", "-created_at")
        .first()
    )


def get_pdf_private_path(pdf_document: PDFDocument) -> Path:
    root = get_private_document_root().resolve()
    path = (root / pdf_document.storage_key).resolve()
    if root not in path.parents and path != root:
        raise ValidationError("Ungueltiger interner Dokumentpfad.")
    return path


def generate_entry_pdf_document(*, form_entry: FormEntry, user, document_kind: str | None = None) -> PDFDocument:
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise ValidationError(
            "WeasyPrint ist noch nicht installiert. Bitte Abhaengigkeiten installieren, bevor PDF-Dateien erzeugt werden."
        ) from exc

    document_kind = document_kind or PDFDocument.DocumentKind.REVIEW
    now = timezone.now()
    html = render_entry_pdf_html(form_entry=form_entry, generated_by=user)
    pdf_bytes = HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    storage_key = (
        f"pdf_documents/{form_entry.pk}/{document_kind}/"
        f"{now.strftime('%Y%m%d_%H%M%S')}_{sha256[:12]}.pdf"
    )
    target_path = (get_private_document_root() / storage_key).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(pdf_bytes)

    pdf_document = PDFDocument.objects.create(
        form=form_entry.form,
        form_entry=form_entry,
        bewohner=form_entry.bewohner,
        document_kind=document_kind,
        status=PDFDocument.GenerationStatus.GENERATED,
        storage_key=storage_key,
        original_filename=f"{form_entry.form.key}_{form_entry.public_id}.pdf",
        content_type="application/pdf",
        file_size=len(pdf_bytes),
        sha256=sha256,
        generated_at=now,
        access_policy={
            "private": True,
            "generated_by": str(user.pk) if user else None,
            "download_requires_permission": True,
        },
        created_by=user,
        updated_by=user,
    )

    AuditLog.objects.create(
        actor=user,
        event_type=AuditLog.EventType.PDF_RENDERED,
        target_model="PDFDocument",
        target_id=pdf_document.pk,
        bewohner=form_entry.bewohner,
        form=form_entry.form,
        form_entry=form_entry,
        message="PDF-Vorschau wurde erzeugt und privat gespeichert.",
        metadata={"pdf_document_id": str(pdf_document.pk), "sha256": sha256},
    )
    return pdf_document
