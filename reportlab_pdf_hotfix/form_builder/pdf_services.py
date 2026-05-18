from __future__ import annotations

import hashlib
from copy import copy
from io import BytesIO
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
    if "T" in text:
        text = text.split("T", 1)[0]
    parts = text.split("-")
    if len(parts) == 3 and all(parts):
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return text


def _display_value(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, ""))
    if value is True:
        return "Ja"
    if value is False:
        return "Nein"
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


def _import_reportlab():
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise ValidationError(
            "ReportLab ist noch nicht installiert. Bitte python -m pip install reportlab ausfuehren."
        ) from exc
    return {
        "colors": colors,
        "TA_CENTER": TA_CENTER,
        "TA_LEFT": TA_LEFT,
        "A4": A4,
        "landscape": landscape,
        "ParagraphStyle": ParagraphStyle,
        "getSampleStyleSheet": getSampleStyleSheet,
        "mm": mm,
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


def _p(text, style):
    rl = _RL_CACHE
    Paragraph = rl["Paragraph"]
    safe = "" if text is None else str(text)
    safe = safe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, style)


def _build_styles():
    rl = _RL_CACHE
    ParagraphStyle = rl["ParagraphStyle"]
    TA_CENTER = rl["TA_CENTER"]
    TA_LEFT = rl["TA_LEFT"]
    return {
        "title": ParagraphStyle(
            "GovTitle",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=16,
            alignment=TA_CENTER,
            spaceAfter=5,
        ),
        "subtitle": ParagraphStyle(
            "GovSubtitle",
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=rl["colors"].HexColor("#334155"),
            spaceAfter=8,
        ),
        "cell": ParagraphStyle(
            "GovCell", fontName="Helvetica", fontSize=7.2, leading=8.4, alignment=TA_LEFT
        ),
        "cell_center": ParagraphStyle(
            "GovCellCenter", fontName="Helvetica", fontSize=7.2, leading=8.4, alignment=TA_CENTER
        ),
        "head": ParagraphStyle(
            "GovHead", fontName="Helvetica-Bold", fontSize=7.5, leading=8.5, alignment=TA_CENTER
        ),
        "red_head": ParagraphStyle(
            "GovRedHead",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=8.5,
            alignment=TA_CENTER,
            textColor=rl["colors"].HexColor("#b91c1c"),
        ),
        "label": ParagraphStyle(
            "GovLabel", fontName="Helvetica-Bold", fontSize=8.5, leading=10, alignment=TA_LEFT
        ),
        "value": ParagraphStyle(
            "GovValue", fontName="Helvetica", fontSize=9, leading=11, alignment=TA_LEFT
        ),
        "small": ParagraphStyle(
            "GovSmall",
            fontName="Helvetica",
            fontSize=7,
            leading=8.5,
            alignment=TA_LEFT,
            textColor=rl["colors"].HexColor("#475569"),
        ),
    }


def _make_document(buffer: BytesIO, *, pagesize):
    rl = _RL_CACHE
    mm = rl["mm"]
    return rl["SimpleDocTemplate"](
        buffer,
        pagesize=pagesize,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title="Formularvorschau",
        author=getattr(settings, "PDF_COMPANY_NAME", "Bewohnerformular"),
    )


def _render_sozialticket_pdf(
    form_entry: FormEntry, *, generated_by=None, data_override: dict | None = None
) -> bytes:
    rl = _RL_CACHE
    colors = rl["colors"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Spacer = rl["Spacer"]
    mm = rl["mm"]
    styles = _build_styles()
    buffer = BytesIO()
    doc = _make_document(buffer, pagesize=rl["landscape"](rl["A4"]))
    rows = build_sozialticket_rows(form_entry, data_override=data_override, total_rows=25)

    story = [
        _p("Sozialticket Antrag", styles["title"]),
        _p(
            "Revisionsfaehige Formularvorschau - Eingaben werden live uebernommen",
            styles["subtitle"],
        ),
    ]
    header = [
        _p("Datum", styles["head"]),
        _p("Dias", styles["head"]),
        _p("PKZ", styles["head"]),
        _p("Name", styles["head"]),
        _p("Vorname", styles["head"]),
        _p("geb. am", styles["head"]),
        _p("Geschlecht", styles["head"]),
        _p("Grund", styles["red_head"]),
    ]
    data = [header]
    for row in rows:
        data.append(
            [
                _p(row["datum"], styles["cell_center"]),
                _p(row["dias"], styles["cell_center"]),
                _p(row["pkz"], styles["cell_center"]),
                _p(row["name"], styles["cell"]),
                _p(row["vorname"], styles["cell"]),
                _p(row["geb_am"], styles["cell_center"]),
                _p(row["geschlecht"], styles["cell_center"]),
                _p(row["grund"], styles["cell_center"]),
            ]
        )
    table = Table(
        data,
        colWidths=[24 * mm, 20 * mm, 28 * mm, 48 * mm, 40 * mm, 28 * mm, 28 * mm, 35 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf1f8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fbfdff")]),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(
        _p(
            f"Erzeugt: {timezone.localtime(timezone.now()).strftime('%d.%m.%Y %H:%M')} | Benutzer: {getattr(generated_by, 'username', '') or '-'}",
            styles["small"],
        )
    )
    doc.build(story)
    return buffer.getvalue()


def _render_official_pdf(
    form_entry: FormEntry, *, generated_by=None, data_override: dict | None = None
) -> bytes:
    rl = _RL_CACHE
    colors = rl["colors"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Spacer = rl["Spacer"]
    mm = rl["mm"]
    styles = _build_styles()
    buffer = BytesIO()
    doc = _make_document(buffer, pagesize=rl["A4"])
    form_title = getattr(form_entry.form, "title", "Formular")
    form_desc = getattr(form_entry.form, "description", "")
    rows = build_official_rows(form_entry, data_override=data_override)

    story = [_p(form_title, styles["title"])]
    if form_desc:
        story.append(_p(form_desc, styles["subtitle"]))
    story.append(Spacer(1, 3 * mm))
    meta = [
        [
            _p("Vorgang", styles["label"]),
            _p(str(getattr(form_entry, "public_id", ""))[:18], styles["value"]),
            _p("Status", styles["label"]),
            _p(getattr(form_entry, "status", "Entwurf"), styles["value"]),
        ],
        [
            _p("Erzeugt", styles["label"]),
            _p(timezone.localtime(timezone.now()).strftime("%d.%m.%Y %H:%M"), styles["value"]),
            _p("Benutzer", styles["label"]),
            _p(getattr(generated_by, "username", "") or "-", styles["value"]),
        ],
    ]
    meta_table = Table(meta, colWidths=[28 * mm, 62 * mm, 28 * mm, 62 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef3f8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 6 * mm))

    table_data = [[_p("Feld", styles["head"]), _p("Eintragung", styles["head"])]]
    for row in rows:
        table_data.append(
            [_p(row["label"], styles["label"]), _p(row["value"] or "", styles["value"])]
        )
    table = Table(table_data, colWidths=[55 * mm, 125 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#64748b")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
                ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f8fafc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return buffer.getvalue()


def _render_generic_pdf(
    form_entry: FormEntry, *, generated_by=None, data_override: dict | None = None
) -> bytes:
    return _render_official_pdf(form_entry, generated_by=generated_by, data_override=data_override)


def render_entry_pdf_bytes(
    *, form_entry: FormEntry, generated_by=None, data_override: dict | None = None
) -> bytes:
    global _RL_CACHE
    _RL_CACHE = _import_reportlab()
    form_key = getattr(form_entry.form, "key", "")
    if form_key == SOZIALTICKET_FORM_KEY:
        return _render_sozialticket_pdf(
            form_entry, generated_by=generated_by, data_override=data_override
        )
    return _render_official_pdf(form_entry, generated_by=generated_by, data_override=data_override)


_RL_CACHE = None


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
        metadata={
            "pdf_document_id": str(pdf_document.pk),
            "sha256": sha256,
            "renderer": "reportlab",
        },
    )
    return pdf_document
