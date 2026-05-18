from __future__ import annotations

import base64
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
FREIWILLIGE_RUECKKEHR_FORM_KEY = "freiwillige-rueckkehr"
BZR_SPRECHSTUNDE_FORM_KEY = "bzr-woechentliche-sprechstunde"
AB_SPRECHSTUNDE_FORM_KEY = "ab-sprechstundenliste"
BESCHWERDEBOGEN_FORM_KEY = "beschwerdebogen-zue-weeze"
BV_FORM_KEY = "meldung-besonderes-vorkommnis"

COLLECTIVE_TABLE_CONFIGS = {
    FREIWILLIGE_RUECKKEHR_FORM_KEY: {
        "title": "Freiwillige Rückkehr",
        "subtitle": "Offene Sammelliste - Einträge bleiben bis zum Versand in dieser Tabelle",
        "total_rows": 14,
        "row_height_mm": 7.4,
        "color": "#eaf1f8",
        "headers": ["PKZ", "Name", "Vorname", "Geb.-Dat.", "DIAS", "Datum", "Restbar Geld"],
        "keys": ["pkz", "name", "vorname", "geb_am", "dias", "datum", "restbetrag_geld"],
        "widths": [27, 49, 49, 36, 34, 36, 44],
    },
    BZR_SPRECHSTUNDE_FORM_KEY: {
        "title": "BZR wöchentliche Sprechstunde",
        "subtitle": "Bezirksregierung Düsseldorf - offene Termin- und Gesprächsliste",
        "total_rows": 10,
        "color": "#eaf1f8",
        "headers": ["Nr.", "EXT", "PKZ", "Name", "Vorname", "Datum", "Uhrzeit", "Grund", "SB Name"],
        "keys": ["nr", "ext", "pkz", "name", "vorname", "datum", "uhrzeit", "grund", "sb_name"],
        "widths": [12, 24, 28, 40, 38, 28, 24, 45, 35],
    },
    AB_SPRECHSTUNDE_FORM_KEY: {
        "title": "AB Sprechstundenliste",
        "subtitle": "Offene Sprechstundenliste - Einträge werden gesammelt und nach Versand archiviert",
        "total_rows": 14,
        "row_height_mm": 7.6,
        "color": "#d9efcf",
        "headers": ["PKZ", "Name", "Vorname", "Geb.Datum", "Grund"],
        "keys": ["pkz", "name", "vorname", "geb_am", "grund"],
        "widths": [36, 55, 55, 42, 89],
    },
    LEISTUNGSBESCHEID_FORM_KEY: {
        "title": "Leistungsbescheid",
        "subtitle": "Offene Sammelliste - Leistungsbescheide bis zum Versand",
        "total_rows": 16,
        "row_height_mm": 8.7,
        "color": "#dbeafe",
        "headers": ["Datum", "Dias", "PKZ", "Name", "Vorname", "geb. am", "Grund"],
        "keys": ["datum", "dias", "pkz", "name", "vorname", "geb_am", "grund"],
        "widths": [30, 30, 34, 50, 44, 34, 55],
    },
}


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
        if (field_definition.get("ui_config") or {}).get("widget") == "signature":
            value = "Unterschrieben" if raw_value not in (None, "") else "-"
        elif isinstance(raw_value, list):
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


def _entry_to_sozialticket_row(form_entry, *, data_override: dict | None = None) -> dict:
    entry_data = _data_for(form_entry, data_override)
    bewohner = getattr(form_entry, "bewohner", None)
    return {
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


def _open_sozialticket_entries(form, *, exclude_pk=None):
    """All Sozialticket rows that still belong to the current unsent collective form."""
    try:
        from .models import FormEntry
    except Exception:  # pragma: no cover - only used during early imports
        return []
    open_statuses = [
        FormEntry.EntryStatus.DRAFT,
        FormEntry.EntryStatus.REJECTED,
        FormEntry.EntryStatus.IN_REVIEW,
        FormEntry.EntryStatus.APPROVED,
        FormEntry.EntryStatus.READY_TO_SEND,
    ]
    queryset = (
        FormEntry.objects.select_related("form", "bewohner")
        .filter(form=form, status__in=open_statuses)
        .order_by("created_at", "updated_at")
    )
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    return list(queryset)


def build_sozialticket_rows(
    form_entry, *, data_override: dict | None = None, total_rows: int = 25
) -> list[dict]:
    """Build the current collective Sozialticket table.

    Important workflow rule: Sozialticket is a Sammelformular. Every unsent
    entry of this form stays in the same PDF table. When an entry is sent and
    archived, it disappears from this open table and the next new entry starts
    a fresh open collective list.
    """
    rows = []
    current_pk = getattr(form_entry, "pk", None)
    rows.append(_entry_to_sozialticket_row(form_entry, data_override=data_override))
    for entry in _open_sozialticket_entries(
        getattr(form_entry, "form", None), exclude_pk=current_pk
    ):
        rows.append(_entry_to_sozialticket_row(entry))
    if not rows:
        rows.append(
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
        )
    minimum_rows = max(total_rows, len(rows))
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
        for _ in range(max(minimum_rows - len(rows), 0))
    )
    return rows


def _open_entries_for_collective(form, *, exclude_pk=None):
    try:
        from .models import FormEntry
    except Exception:  # pragma: no cover
        return []
    open_statuses = [
        FormEntry.EntryStatus.DRAFT,
        FormEntry.EntryStatus.REJECTED,
        FormEntry.EntryStatus.IN_REVIEW,
        FormEntry.EntryStatus.APPROVED,
        FormEntry.EntryStatus.READY_TO_SEND,
    ]
    queryset = (
        FormEntry.objects.select_related("form", "bewohner")
        .filter(form=form, status__in=open_statuses)
        .order_by("created_at", "updated_at")
    )
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    return list(queryset)


def _value_for_key(
    form_entry, key: str, *, data_override: dict | None = None, row_number: int | None = None
) -> str:
    if key == "nr":
        return str(row_number or "")
    entry_data = _data_for(form_entry, data_override)
    bewohner = getattr(form_entry, "bewohner", None)
    value = entry_data.get(key)
    if key in {"datum", "geb_am", "gueltig_ab", "gueltig_bis", "geburtsdatum"}:
        value = _display_date(
            value or getattr(bewohner, "date_of_birth", "") if key == "geb_am" else value
        )
    elif key == "name":
        value = _display_value(value) or getattr(bewohner, "last_name", "") or ""
    elif key == "vorname":
        value = _display_value(value) or getattr(bewohner, "first_name", "") or ""
    else:
        value = _display_value(value)
    return value


def build_collective_table_rows(
    form_entry, config: dict, *, data_override: dict | None = None
) -> list[dict]:
    current_pk = getattr(form_entry, "pk", None)
    entries = [(form_entry, data_override)]
    entries.extend(
        (entry, None)
        for entry in _open_entries_for_collective(
            getattr(form_entry, "form", None), exclude_pk=current_pk
        )
    )
    rows = []
    for index, (entry, override) in enumerate(entries, start=1):
        rows.append(
            {
                key: _value_for_key(entry, key, data_override=override, row_number=index)
                for key in config["keys"]
            }
        )
    minimum_rows = max(config.get("total_rows", 12), len(rows))
    while len(rows) < minimum_rows:
        rows.append({key: str(len(rows) + 1) if key == "nr" else "" for key in config["keys"]})
    return rows


def build_complaint_context(form_entry, *, data_override: dict | None = None) -> dict:
    entry_data = _data_for(form_entry, data_override)
    categories = [
        ("sozialbetreuung", "Sozialbetreuung"),
        ("kinderbetreuung", "Kinderbetreuung"),
        ("hausmeister", "Hausmeister"),
        ("sicherheit", "Sicherheit"),
        ("deutschkurs", "Deutschkurs"),
        ("bezirksregierung", "Bezirksregierung"),
        ("mensa", "Mensa"),
        ("schule", "Schule"),
        ("sonstiges", "Sonstiges"),
    ]
    selected = set(entry_data.get("beschwerde_ueber") or [])
    return {
        "beschwerde_von": _display_value(entry_data.get("beschwerde_von")),
        "datum": _display_date(entry_data.get("datum")),
        "erlaeuterung": _display_value(entry_data.get("erlaeuterung")),
        "categories": [(key, label, key in selected) for key, label in categories],
    }


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
    elif form_key in COLLECTIVE_TABLE_CONFIGS:
        context["collective_config"] = COLLECTIVE_TABLE_CONFIGS[form_key]
        context["collective_rows"] = build_collective_table_rows(
            preview_entry, COLLECTIVE_TABLE_CONFIGS[form_key], data_override=data_override
        )
    elif form_key == BESCHWERDEBOGEN_FORM_KEY:
        context["complaint"] = build_complaint_context(preview_entry, data_override=data_override)
    elif form_key == ZAP_TERMIN_FORM_KEY:
        context["official_rows"] = build_official_rows(preview_entry, data_override=data_override)
    return context


def get_pdf_template(form_entry: FormEntry) -> str:
    form_key = getattr(form_entry.form, "key", "")
    if form_key == SOZIALTICKET_FORM_KEY:
        return SOZIALTICKET_TEMPLATE
    if form_key in COLLECTIVE_TABLE_CONFIGS or form_key == BESCHWERDEBOGEN_FORM_KEY:
        return OFFICIAL_TABLE_TEMPLATE
    if form_key == ZAP_TERMIN_FORM_KEY:
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
        from reportlab.platypus import (
            Image,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
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
        "Image": Image,
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
            "Offene Sammelliste - neue Anträge bleiben bis zum Versand in dieser Tabelle",
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
            f"Offene Liste bis Versand | Erzeugt: {timezone.localtime(timezone.now()).strftime('%d.%m.%Y %H:%M')} | Benutzer: {getattr(generated_by, 'username', '') or '-'}",
            styles["small"],
        )
    )
    doc.build(story)
    return buffer.getvalue()


def _render_collective_table_pdf(
    form_entry: FormEntry, config: dict, *, generated_by=None, data_override: dict | None = None
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
    rows = build_collective_table_rows(form_entry, config, data_override=data_override)

    story = [
        _p(config["title"], styles["title"]),
        _p(config.get("subtitle", ""), styles["subtitle"]),
    ]
    header = [_p(label, styles["head"]) for label in config["headers"]]
    data = [header]
    for row in rows:
        data.append(
            [
                _p(
                    row.get(key, ""),
                    styles[
                        (
                            "cell_center"
                            if key in {"nr", "datum", "geb_am", "dias", "pkz", "ext", "uhrzeit"}
                            else "cell"
                        )
                    ],
                )
                for key in config["keys"]
            ]
        )
    row_height = config.get("row_height_mm")
    row_heights = None
    if row_height:
        row_heights = [7.0 * mm] + [row_height * mm for _ in rows]
    table = Table(
        data, colWidths=[w * mm for w in config["widths"]], rowHeights=row_heights, repeatRows=1
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.55, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(config.get("color", "#eaf1f8"))),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fbff")]),
                ("TOPPADDING", (0, 0), (-1, -1), 2.8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
                ("LEFTPADDING", (0, 0), (-1, -1), 3.2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3.2),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(
        _p(
            f"Offene Liste bis Versand | Erzeugt: {timezone.localtime(timezone.now()).strftime('%d.%m.%Y %H:%M')} | Benutzer: {getattr(generated_by, 'username', '') or '-'}",
            styles["small"],
        )
    )
    doc.build(story)
    return buffer.getvalue()


def _signature_image_flowable(value: str, *, width_mm: float = 62, height_mm: float = 20):
    """Convert a browser canvas data URL into a ReportLab Image flowable."""
    if not value or not isinstance(value, str) or not value.startswith("data:image/"):
        return None
    try:
        _, payload = value.split(",", 1)
        image_bytes = base64.b64decode(payload)
        image = _RL_CACHE["Image"](
            BytesIO(image_bytes),
            width=width_mm * _RL_CACHE["mm"],
            height=height_mm * _RL_CACHE["mm"],
        )
        image.hAlign = "CENTER"
        return image
    except Exception:
        return None


def _render_complaint_pdf(
    form_entry: FormEntry, *, generated_by=None, data_override: dict | None = None
) -> bytes:
    rl = _RL_CACHE
    colors = rl["colors"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Spacer = rl["Spacer"]
    mm = rl["mm"]
    styles = _build_styles()
    ctx = build_complaint_context(form_entry, data_override=data_override)
    buffer = BytesIO()
    doc = _make_document(buffer, pagesize=rl["A4"])
    story = [
        _p("Beschwerdebogen ZUE-Weeze II", styles["title"]),
        _p("Beschwerdeaufnahme und interne Weiterleitung", styles["subtitle"]),
        Spacer(1, 6 * mm),
    ]
    head = [
        [
            _p("Beschwerde von:", styles["label"]),
            _p(ctx["beschwerde_von"], styles["value"]),
            _p("Datum:", styles["label"]),
            _p(ctx["datum"], styles["value"]),
        ]
    ]
    head_table = Table(head, colWidths=[38 * mm, 72 * mm, 24 * mm, 46 * mm])
    head_table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (1, 0), (1, 0), 0.8, colors.black),
                ("LINEBELOW", (3, 0), (3, 0), 0.8, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(head_table)
    story.append(Spacer(1, 10 * mm))
    story.append(_p("Beschwerde über:", styles["label"]))
    cats = ctx["categories"]
    cat_rows = []
    for i in range(0, len(cats), 3):
        row = []
        for key, label, checked in cats[i : i + 3]:
            row.append(_p(("[x] " if checked else "[ ] ") + label, styles["value"]))
        while len(row) < 3:
            row.append(_p("", styles["value"]))
        cat_rows.append(row)
    cat_table = Table(cat_rows, colWidths=[60 * mm, 60 * mm, 60 * mm])
    cat_table.setStyle(
        TableStyle([("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])
    )
    story.append(cat_table)
    story.append(Spacer(1, 10 * mm))
    story.append(_p("Erläuterung:", styles["label"]))
    text_lines = (ctx["erlaeuterung"] or "").splitlines() or [""]
    line_rows = []
    for i in range(12):
        text = text_lines[i] if i < len(text_lines) else ""
        line_rows.append([_p(text, styles["value"])])
    text_table = Table(line_rows, colWidths=[180 * mm], rowHeights=[9 * mm] * 12)
    text_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.0, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#94a3b8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(text_table)
    story.append(Spacer(1, 14 * mm))
    entry_data = _data_for(form_entry, data_override)
    sig_left = _signature_image_flowable(
        entry_data.get("unterschrift_beschwerdefuehrer", "")
    ) or _p("", styles["small"])
    sig_right = _signature_image_flowable(entry_data.get("unterschrift_aufnehmer", "")) or _p(
        "", styles["small"]
    )
    sig_table = Table(
        [
            [sig_left, _p("", styles["small"]), sig_right],
            [
                _p("Unterschrift Beschwerdeführer", styles["small"]),
                _p("", styles["small"]),
                _p("Unterschrift Beschwerdeaufnehmer", styles["small"]),
            ],
        ],
        colWidths=[70 * mm, 35 * mm, 70 * mm],
        rowHeights=[22 * mm, 7 * mm],
    )
    sig_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LINEABOVE", (0, 1), (0, 1), 0.8, colors.black),
                ("LINEABOVE", (2, 1), (2, 1), 0.8, colors.black),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "CENTER"),
            ]
        )
    )
    story.append(sig_table)
    doc.build(story)
    return buffer.getvalue()


def _draw_wrapped_text(
    c,
    text: str,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    font="Helvetica",
    font_size=7.0,
    leading=8.2,
    color=None,
    max_lines: int | None = None,
):
    """Draw text inside a rectangle, clipping by line count rather than overflowing."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if color is not None:
        c.setFillColor(color)
    c.setFont(font, font_size)
    raw = "" if text is None else str(text)
    paragraphs = raw.replace("\r", "").split("\n") or [""]
    lines = []
    for paragraph in paragraphs:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if stringWidth(candidate, font, font_size) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    allowed = max(1, int((height - 3) // leading))
    if max_lines is not None:
        allowed = min(allowed, max_lines)
    lines = lines[:allowed]
    text_obj = c.beginText(x, y - font_size)
    text_obj.setFont(font, font_size)
    text_obj.setLeading(leading)
    for line in lines:
        text_obj.textLine(line)
    c.drawText(text_obj)


def _select_label(value) -> str:
    return _display_value(value) or "-"


def _render_bv_pdf(
    form_entry: FormEntry, *, generated_by=None, data_override: dict | None = None
) -> bytes:
    """Render Meldung Besonderes Vorkommnis (BV) as a stable one-page form.

    The layout intentionally uses fixed page coordinates.  It mirrors the provided
    official BV template more closely than the generic table renderer and avoids
    the previous issue where the lower sections were pushed outside the page.
    """
    rl = _RL_CACHE
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    colors = rl["colors"]
    mm = rl["mm"]
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=rl["A4"])
    page_w, page_h = rl["A4"]
    data = _data_for(form_entry, data_override)

    dark = colors.HexColor("#111827")
    muted = colors.HexColor("#475569")
    field_fill = colors.HexColor("#dfe8ff")
    white = colors.white

    def raw(key):
        return data.get(key)

    def val(key):
        if key == "datum":
            return _display_date(data.get(key))
        return _display_value(data.get(key))

    def label(text, x, y, size=5.8):
        c.setFillColor(dark)
        c.setFont("Helvetica-Bold", size)
        c.drawString(x, y, text)

    def draw_text_fit(
        text, x, y, w, h, *, font="Helvetica", size=6.8, max_lines=None, center=False
    ):
        text = "" if text is None else str(text)
        c.setFillColor(dark)
        if center:
            c.setFont(font, size)
            c.drawCentredString(x + w / 2, y + h / 2 - size / 3, text[:80])
            return
        paragraphs = text.replace("\r", "").split("\n") or [""]
        lines = []
        for para in paragraphs:
            words = para.split()
            if not words:
                lines.append("")
                continue
            cur = ""
            for word in words:
                cand = word if not cur else cur + " " + word
                if stringWidth(cand, font, size) <= w - 4:
                    cur = cand
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
        leading = size + 1.6
        allowed = max(1, int((h - 4) // leading))
        if max_lines is not None:
            allowed = min(allowed, max_lines)
        lines = lines[:allowed]
        t = c.beginText(x + 2.0, y + h - size - 2.0)
        t.setFont(font, size)
        t.setLeading(leading)
        for line in lines:
            t.textLine(line)
        c.drawText(t)

    def draw_box(x, y, w, h, text="", *, fill=field_fill, font_size=6.6, center=False, lw=0.75):
        c.setStrokeColor(dark)
        c.setLineWidth(lw)
        c.setFillColor(fill)
        c.rect(x, y, w, h, fill=1, stroke=1)
        if text not in (None, ""):
            draw_text_fit(text, x, y, w, h, size=font_size, center=center)

    def draw_select(x, y, w, h, text=""):
        draw_box(x, y, w, h, _select_label(text), font_size=6.3, lw=0.8)
        marker_w = 13.0
        c.setStrokeColor(colors.HexColor("#94a3b8"))
        c.setLineWidth(0.45)
        c.line(x + w - marker_w, y, x + w - marker_w, y + h)
        # draw a small down-arrow with lines, not a Unicode glyph (avoids black squares)
        cx = x + w - marker_w / 2
        cy = y + h / 2 + 0.5
        c.setStrokeColor(dark)
        c.setLineWidth(0.7)
        c.line(cx - 2.0, cy + 1.0, cx, cy - 1.2)
        c.line(cx, cy - 1.2, cx + 2.0, cy + 1.0)

    def draw_checkbox(x, y, checked=False):
        c.setStrokeColor(dark)
        c.setLineWidth(0.7)
        c.setFillColor(field_fill if checked else white)
        c.rect(x, y, 9.0, 9.0, fill=1, stroke=1)
        if checked:
            c.setFillColor(dark)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(x + 2.0, y + 1.7, "x")

    left = 47.0
    right = page_w - 47.0
    usable = right - left

    # Header
    title_y = 807.0
    c.setFillColor(dark)
    c.setFont("Helvetica-Bold", 13.0)
    c.drawCentredString(page_w / 2, title_y, "Meldung Besonderes Vorkommnis (BV)")
    c.setFillColor(colors.HexColor("#0f766e"))
    c.circle(right - 75, title_y - 2, 9, fill=1, stroke=0)
    c.setFillColor(muted)
    c.setFont("Helvetica", 7.8)
    c.drawRightString(right, title_y - 1, "EUROPEAN")
    c.setFont("Helvetica-Bold", 10.0)
    c.drawRightString(right, title_y - 12, "homecare")

    # 1-4 header fields
    y = 740.0
    field_h = 20.5
    widths = [94.0, 165.0, 95.0, usable - 94.0 - 165.0 - 95.0]
    labels = ["1. Datum:", "2. Einrichtung:", "3. LfdNr.:", "4. Meldender (Name/Position):"]
    keys = ["datum", "einrichtung", "lfd_nr", "meldender"]
    x = left
    for w, lab, key in zip(widths, labels, keys):
        label(lab, x, y + field_h + 5.2, size=5.7)
        draw_box(x, y, w, field_h, val(key), font_size=7.0)
        x += w

    # 5 Art des Vorfalls
    y = 685.0
    label("5. Art des Vorfalls:", left, y + 27.5, size=5.7)
    gap = 3.0
    select_w = (usable - 2 * gap) / 3
    for i, key in enumerate(["art_vorfall_1", "art_vorfall_2", "art_vorfall_3"]):
        draw_select(left + i * (select_w + gap), y, select_w, 22.0, raw(key))

    y = 657.0
    draw_checkbox(left, y + 3.0, bool(raw("sonstiges")))
    label("Sonstiges", left + 31.0, y + 5.0, size=5.8)
    draw_box(left + 72.0, y, usable - 72.0, 14.0, val("sonstiges_text"), font_size=6.2)

    # 6 Zeitliche Abfolge + 6.1 Sachverhalt
    body_top = 626.0
    body_h = 230.0
    body_bottom = body_top - body_h
    time_w = 94.0
    rows = 8
    row_h = body_h / rows
    label("6. Zeitliche Abfolge:", left, body_top + 5.5, size=5.6)
    label(
        "6.1 Sachverhalt (wer, was, wie, wo, warum) und Schilderung der Maßnahmen:",
        left + time_w + 2.0,
        body_top + 5.5,
        size=5.4,
    )
    for i in range(rows):
        row_y = body_top - (i + 1) * row_h
        draw_box(left, row_y, time_w, row_h, val(f"zeit{i + 1}"), font_size=6.3, center=False)
    draw_box(left + time_w, body_bottom, usable - time_w, body_h, "", font_size=6.2)
    draw_text_fit(
        val("sachverhalt"),
        left + time_w + 2.0,
        body_bottom + 2.0,
        usable - time_w - 4.0,
        body_h - 4.0,
        size=6.5,
    )

    # 7 Beteiligte Personen
    label_y = body_bottom - 17.0
    label(
        "7. Beteiligte Personen: Bezeichnung / Name, Vorname / Nationalität.",
        left,
        label_y,
        size=5.5,
    )
    part_label_w = 61.0
    part_h = 35.0
    part_top = label_y - 7.0
    participants = [
        ("7.1 Täter:", "taeter"),
        ("7.2 Geschädigte:", "geschaedigte"),
        ("7.3 Zeugen:", "zeugen"),
    ]
    for idx, (lab, key) in enumerate(participants):
        row_y = part_top - (idx + 1) * part_h
        label(lab, left, row_y + part_h - 10.0, size=5.6)
        draw_box(left + part_label_w, row_y, usable - part_label_w, part_h, val(key), font_size=6.2)

    # 8 / 9 / 10 bottom fields
    y = 128.0
    label("8. Einsatz von:", left, y + 26.5, size=5.6)
    for i, key in enumerate(["einsatz_1", "einsatz_2", "einsatz_3"]):
        draw_select(left + i * (select_w + gap), y, select_w, 21.5, raw(key))

    y = 84.0
    label("9. Wer wurde informiert:", left, y + 26.5, size=5.6)
    for i, key in enumerate(["info_1", "info_2", "info_3"]):
        draw_select(left + i * (select_w + gap), y, select_w, 21.5, raw(key))

    y = 42.0
    label("10. Vorgang:", left, y + 18.5, size=5.6)
    draw_select(left + 62.0, y, usable - 62.0, 21.5, raw("vorgang"))

    # Footer
    footer_y = 14.0
    c.setFillColor(muted)
    c.setFont("Helvetica", 5.3)
    c.drawString(
        left, footer_y, f"Erzeugt: {timezone.localtime(timezone.now()).strftime('%d.%m.%Y %H:%M')}"
    )
    c.drawCentredString(page_w / 2, footer_y, "Erstellt durch: Sicherheitsmanagement EHC")
    c.drawRightString(right, footer_y, "Revision: 17.03.2020")

    c.showPage()
    c.save()
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
    if form_key in COLLECTIVE_TABLE_CONFIGS:
        return _render_collective_table_pdf(
            form_entry,
            COLLECTIVE_TABLE_CONFIGS[form_key],
            generated_by=generated_by,
            data_override=data_override,
        )
    if form_key == BESCHWERDEBOGEN_FORM_KEY:
        return _render_complaint_pdf(
            form_entry, generated_by=generated_by, data_override=data_override
        )
    if form_key == BV_FORM_KEY:
        return _render_bv_pdf(form_entry, generated_by=generated_by, data_override=data_override)
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
