from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import AuditLog, Field, FormEntry
from .pdf_template_models import (
    PDFTemplate,
    PDFTemplatePlacement,
    calculate_file_sha256,
    validate_pdf_upload,
)


def _import_pdf_stack():
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise ValidationError("pypdf ist nicht installiert. Bitte `poetry add pypdf` ausfuehren.") from exc
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise ValidationError("ReportLab ist fuer PDF-Vorlagen erforderlich.") from exc
    return PdfReader, PdfWriter, canvas, ImageReader


def _page_size(page) -> tuple[float, float]:
    media_box = page.mediabox
    return float(media_box.width), float(media_box.height)


def analyze_pdf_template_file(file_obj) -> list[dict]:
    PdfReader, _PdfWriter, _canvas, _ImageReader = _import_pdf_stack()
    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        reader = PdfReader(file_obj)
    except Exception as exc:
        raise ValidationError("Die PDF-Vorlage konnte nicht gelesen werden.") from exc
    metadata = []
    for index, page in enumerate(reader.pages, start=1):
        width, height = _page_size(page)
        metadata.append(
            {
                "page_number": index,
                "width": round(width, 3),
                "height": round(height, 3),
                "rotation": int(page.get("/Rotate", 0) or 0),
            }
        )
    if not metadata:
        raise ValidationError("Die PDF-Vorlage enthaelt keine Seiten.")
    return metadata


def create_pdf_template_from_upload(*, form, uploaded_file, user, name: str = "") -> PDFTemplate:
    validate_pdf_upload(uploaded_file)
    page_metadata = analyze_pdf_template_file(uploaded_file)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    sha256 = calculate_file_sha256(uploaded_file)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    template = PDFTemplate.objects.create(
        form=form,
        name=name.strip() or getattr(uploaded_file, "name", "PDF-Vorlage"),
        original_filename=getattr(uploaded_file, "name", "template.pdf")[:255],
        file=uploaded_file,
        content_type="application/pdf",
        file_size=int(getattr(uploaded_file, "size", 0) or 0),
        sha256=sha256,
        page_count=len(page_metadata),
        page_metadata=page_metadata,
        created_by=user,
        updated_by=user,
    )
    AuditLog.objects.create(
        actor=user,
        event_type=AuditLog.EventType.CREATED,
        target_model="PDFTemplate",
        target_id=template.pk,
        form=form,
        message="PDF-Vorlage wurde hochgeladen.",
        metadata={"template_id": str(template.pk), "sha256": sha256, "pages": len(page_metadata)},
    )
    return template


def get_active_pdf_template_for_form(form) -> PDFTemplate | None:
    return (
        PDFTemplate.objects.filter(
            form=form,
            status=PDFTemplate.TemplateStatus.ACTIVE,
            is_active=True,
        )
        .order_by("-updated_at", "-created_at")
        .first()
    )


def _value_for_field(form_entry: FormEntry, field: Field, data_override: dict | None = None):
    data = data_override if data_override is not None else (form_entry.data or {})
    return data.get(field.key, "")


def _display_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    if isinstance(value, dict):
        return str(value.get("filename") or value.get("value") or "")
    text = str(value)
    if "T" in text and len(text) >= 10:
        text = text.split("T", 1)[0]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        year, month, day = text.split("-")
        return f"{day}.{month}.{year}"
    return text


def _checkbox_is_checked(value) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ja", "on", "x"}
    return bool(value)


def _signature_image_bytes(value) -> bytes | None:
    if not isinstance(value, str) or not value.startswith("data:image/") or "," not in value:
        return None
    try:
        return base64.b64decode(value.split(",", 1)[1])
    except Exception:
        return None


def _draw_text(c, *, text: str, x: float, y: float, width: float, height: float, font_size: int):
    if not text:
        return
    c.setFont("Helvetica", font_size)
    max_chars = max(int(width / max(font_size * 0.45, 1)), 1)
    safe = str(text).replace("\r", " ").replace("\n", " ")[: max_chars * 3]
    c.drawString(x, y + max((height - font_size) / 2, 1), safe[:max_chars])


def _draw_checkbox(c, *, checked: bool, x: float, y: float, width: float, height: float):
    size = min(width, height, 14)
    c.rect(x, y + max((height - size) / 2, 0), size, size, stroke=1, fill=0)
    if checked:
        y0 = y + max((height - size) / 2, 0)
        c.setLineWidth(1.4)
        c.line(x + 2, y0 + size * 0.55, x + size * 0.42, y0 + 2)
        c.line(x + size * 0.42, y0 + 2, x + size - 2, y0 + size - 2)
        c.setLineWidth(1)


def _draw_signature(c, *, value, x: float, y: float, width: float, height: float, ImageReader):
    image_bytes = _signature_image_bytes(value)
    if image_bytes:
        c.drawImage(ImageReader(BytesIO(image_bytes)), x, y, width=width, height=height, mask="auto")
    elif value:
        _draw_text(c, text="Unterschrieben", x=x, y=y, width=width, height=height, font_size=9)


def _overlay_for_page(*, page_width: float, page_height: float, placements, form_entry, data_override=None) -> BytesIO:
    _PdfReader, _PdfWriter, canvas, ImageReader = _import_pdf_stack()
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    for placement in placements:
        value = _value_for_field(form_entry, placement.field, data_override=data_override)
        x = placement.x * page_width
        width = placement.width * page_width
        height = placement.height * page_height
        y = page_height - ((placement.y + placement.height) * page_height)
        if placement.kind == PDFTemplatePlacement.PlacementKind.CHECKBOX:
            _draw_checkbox(c, checked=_checkbox_is_checked(value), x=x, y=y, width=width, height=height)
        elif placement.kind == PDFTemplatePlacement.PlacementKind.SIGNATURE:
            _draw_signature(c, value=value, x=x, y=y, width=width, height=height, ImageReader=ImageReader)
        else:
            _draw_text(
                c,
                text=_display_value(value),
                x=x,
                y=y,
                width=width,
                height=height,
                font_size=placement.font_size,
            )
    c.save()
    buffer.seek(0)
    return buffer


def render_pdf_template_bytes(*, form_entry: FormEntry, template: PDFTemplate, data_override=None) -> bytes:
    PdfReader, PdfWriter, _canvas, _ImageReader = _import_pdf_stack()
    with template.file.open("rb") as source:
        reader = PdfReader(source)
        writer = PdfWriter()
        placements_by_page: dict[int, list[PDFTemplatePlacement]] = {}
        for placement in template.placements.select_related("field").filter(is_active=True):
            placements_by_page.setdefault(placement.page_number, []).append(placement)
        for index, page in enumerate(reader.pages, start=1):
            page_width, page_height = _page_size(page)
            placements = placements_by_page.get(index, [])
            if placements:
                overlay_buffer = _overlay_for_page(
                    page_width=page_width,
                    page_height=page_height,
                    placements=placements,
                    form_entry=form_entry,
                    data_override=data_override,
                )
                overlay_reader = PdfReader(overlay_buffer)
                page.merge_page(overlay_reader.pages[0])
            writer.add_page(page)
        output = BytesIO()
        writer.write(output)
    return output.getvalue()


def render_from_template_if_available(*, form_entry: FormEntry, data_override=None) -> bytes | None:
    template = get_active_pdf_template_for_form(form_entry.form)
    if not template:
        return None
    return render_pdf_template_bytes(
        form_entry=form_entry,
        template=template,
        data_override=data_override,
    )


def register_pdf_template_renderer() -> None:
    """Patch the existing renderer without rewriting the legacy pdf_services module."""
    from . import pdf_services

    if getattr(pdf_services, "_PDF_TEMPLATE_RENDERER_REGISTERED", False):
        return
    original_render = pdf_services.render_entry_pdf_bytes

    def wrapped_render_entry_pdf_bytes(*, form_entry, generated_by=None, data_override=None):
        rendered = render_from_template_if_available(form_entry=form_entry, data_override=data_override)
        if rendered is not None:
            return rendered
        return original_render(
            form_entry=form_entry,
            generated_by=generated_by,
            data_override=data_override,
        )

    pdf_services.render_entry_pdf_bytes = wrapped_render_entry_pdf_bytes
    pdf_services._PDF_TEMPLATE_RENDERER_REGISTERED = True


def refresh_template_metadata(template: PDFTemplate, *, user=None) -> PDFTemplate:
    with template.file.open("rb") as handle:
        metadata = analyze_pdf_template_file(handle)
    template.page_metadata = metadata
    template.page_count = len(metadata)
    template.updated_by = user
    template.save(update_fields=["page_metadata", "page_count", "updated_by", "updated_at"])
    return template


def private_template_path(template: PDFTemplate) -> Path:
    return Path(template.file.path)
