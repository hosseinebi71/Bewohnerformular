from __future__ import annotations

import hashlib
from copy import copy
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils import timezone

from .models import AuditLog, FormEntry, PDFDocument

PDF_TEMPLATE = "form_builder/pdf/form_entry_pdf.html"
SOZIALTICKET_TEMPLATE = "form_builder/pdf/sozialticket_antrag_pdf.html"
OFFICIAL_TABLE_TEMPLATE = "form_builder/pdf/official_table_pdf.html"

SOZIALTICKET_FORM_KEY = "sozialticket-antrag"
ZAP_TERMIN_FORM_KEY = "zap-termin"
LEISTUNGSBESCHEID_FORM_KEY = "leistungsbescheid"


def get_private_document_root() -> Path:
    return Path(getattr(settings, "PRIVATE_DOCUMENT_ROOT", settings.BASE_DIR / "private_documents"))


def _data_for(form_entry, data_override: dict | None = None) -> dict:
    return data_override if data_override is not None else (getattr(form_entry, "data", {}) or {})


def get_entry_detail_rows(
    form_entry: FormEntry, *, data_override: dict | None = None
) -> list[dict]:
    rows: list[dict] = []
    schema = getattr(form_entry, "form_snapshot", {}) or {}
    entry_data = _data_for(form_entry, data_override)
    for field_definition in schema.get("fields", []):
        key = field_definition.get("key")
        raw_value = entry_data.get(key, "-")
        if isinstance(raw_value, list):
            value = ", ".join(str(item) for item in raw_value) or "-"
        elif raw_value in (None, ""):
            value = "-"
        else:
            value = raw_value
        rows.append(
            {
                "key": key,
                "label": field_definition.get("label", key or "Feld"),
                "value": value,
                "field_type": field_definition.get("field_type", "text"),
                "sensitivity": field_definition.get("sensitivity", "normal"),
            }
        )
    return rows


def _display_date(value) -> str:
    if not value:
        return ""
    text = str(value)
    parts = text.split("-")
    if len(parts) == 3 and all(parts):
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return text


def _display_value(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, ""))
    if value in (None, ""):
        return ""
    return str(value)


def build_sozialticket_rows(
    form_entry, *, data_override: dict | None = None, total_rows: int = 25
) -> list[dict]:
    entry_data = _data_for(form_entry, data_override)
    bewohner = getattr(form_entry, "bewohner", None)
    first_row = {
        "datum": _display_date(entry_data.get("datum")),
        "dias": _display_value(entry_data.get("dias")),
        "pkz": _display_value(entry_data.get("pkz")),
        "name": _display_value(entry_data.get("name")) or getattr(bewohner, "last_name", "") or "",
        "vorname": _display_value(entry_data.get("vorname"))
        or getattr(bewohner, "first_name", "")
        or "",
        "geb_am": _display_date(entry_data.get("geb_am") or getattr(bewohner, "date_of_birth", "")),
        "geschlecht": _display_value(entry_data.get("geschlecht")),
        "grund": _display_value(entry_data.get("grund")) or "Sozialticket",
    }
    rows = [first_row]
    rows.extend(
        {
            "datum": "",
            "dias": "",
            "pkz": "",
            "name": "",
            "vorname": "",
            "geb_am": "",
            "geschlecht": "",
            "grund": "Sozialticket",
        }
        for _ in range(max(total_rows - 1, 0))
    )
    return rows


def build_official_rows(form_entry, *, data_override: dict | None = None) -> list[dict]:
    entry_data = _data_for(form_entry, data_override)
    schema = getattr(form_entry, "form_snapshot", {}) or {}
    rows = []
    for field in schema.get("fields", []):
        key = field.get("key")
        value = entry_data.get(key)
        if field.get("field_type") in ("date", "datetime"):
            display = _display_date(value)
        else:
            display = _display_value(value)
        rows.append({"label": field.get("label", key or "Feld"), "value": display, "key": key})
    return rows


def build_pdf_context(
    *, form_entry: FormEntry, generated_by=None, data_override: dict | None = None
) -> dict:
    preview_entry = copy(form_entry)
    if data_override is not None:
        preview_entry.data = data_override
    context = {
        "form_entry": preview_entry,
        "detail_rows": get_entry_detail_rows(preview_entry, data_override=data_override),
        "generated_at": timezone.now(),
        "generated_by": generated_by,
        "company_name": getattr(settings, "PDF_COMPANY_NAME", "Bewohner-Formularsystem"),
    }
    form_key = getattr(preview_entry.form, "key", "")
    if form_key == SOZIALTICKET_FORM_KEY:
        context["sozialticket_rows"] = build_sozialticket_rows(
            preview_entry, data_override=data_override
        )
    elif form_key in {ZAP_TERMIN_FORM_KEY, LEISTUNGSBESCHEID_FORM_KEY}:
        context["official_rows"] = build_official_rows(preview_entry, data_override=data_override)
    return context


def get_pdf_template(form_entry: FormEntry) -> str:
    form_key = getattr(form_entry.form, "key", "")
    if form_key == SOZIALTICKET_FORM_KEY:
        return SOZIALTICKET_TEMPLATE
    if form_key in {ZAP_TERMIN_FORM_KEY, LEISTUNGSBESCHEID_FORM_KEY}:
        return OFFICIAL_TABLE_TEMPLATE
    return PDF_TEMPLATE


def render_entry_pdf_html(
    *, form_entry: FormEntry, generated_by=None, data_override: dict | None = None
) -> str:
    return render_to_string(
        get_pdf_template(form_entry),
        build_pdf_context(
            form_entry=form_entry, generated_by=generated_by, data_override=data_override
        ),
    )


def render_entry_pdf_bytes(
    *, form_entry: FormEntry, generated_by=None, data_override: dict | None = None
) -> bytes:
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise ValidationError(
            "WeasyPrint ist noch nicht installiert. Bitte Abhaengigkeiten installieren."
        ) from exc
    html = render_entry_pdf_html(
        form_entry=form_entry, generated_by=generated_by, data_override=data_override
    )
    return HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()


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


def generate_entry_pdf_document(
    *, form_entry: FormEntry, user, document_kind: str | None = None
) -> PDFDocument:
    document_kind = document_kind or PDFDocument.DocumentKind.REVIEW
    now = timezone.now()
    pdf_bytes = render_entry_pdf_bytes(form_entry=form_entry, generated_by=user)
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    storage_key = f"pdf_documents/{form_entry.pk}/{document_kind}/{now.strftime('%Y%m%d_%H%M%S')}_{sha256[:12]}.pdf"
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
