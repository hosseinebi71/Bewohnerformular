from __future__ import annotations


def field(key, label, field_type="text", *, required=False, **extra):
    payload = {"key": key, "label": label, "field_type": field_type, "required": required}
    payload.update(extra)
    return payload


def select(key, label, choices, *, required=False, **extra):
    return field(
        key,
        label,
        "select",
        required=required,
        choices=[{"value": value, "label": label_text} for value, label_text in choices],
        **extra,
    )


STARTER_TEMPLATES = [
    {
        "key": "hygiene-kontrolle",
        "version": 1,
        "title": "Hygiene Kontrolle",
        "category": "Qualitaet & Sicherheit",
        "description": "Kontrollformular mit wiederholbarer Tabelle fuer Kontrollpunkte und Massnahmen.",
        "tags": ["hygiene", "kontrolle", "massnahmen"],
        "definition": {
            "form": {"key": "hygiene-kontrolle", "title": "Hygiene Kontrolle", "review_required": True},
            "sections": [
                {
                    "key": "kopfdaten",
                    "title": "Kopfdaten",
                    "position": 1,
                    "fields": [
                        field("datum", "Datum", "date", required=True),
                        field("bereich", "Bereich / Station", required=True),
                        field("kontrolliert_von", "Kontrolliert von", required=True),
                    ],
                }
            ],
            "repeatable_groups": [
                {
                    "key": "kontrollpunkte",
                    "title": "Kontrollpunkte",
                    "position": 2,
                    "min_rows": 1,
                    "max_rows": 50,
                    "columns": [
                        field("kontrollpunkt", "Kontrollpunkt", "text", required=True),
                        select("bewertung", "Bewertung", [("ok", "OK"), ("nicht_ok", "Nicht OK")], required=True),
                        field("massnahme", "Massnahme", "textarea"),
                        field("verantwortlich", "Verantwortlich", "text"),
                        field("frist", "Frist", "date"),
                    ],
                }
            ],
            "action_item_rules": [
                {
                    "name": "Nicht OK erzeugt Massnahme",
                    "source_group_key": "kontrollpunkte",
                    "source_column_key": "bewertung",
                    "operator": "equals",
                    "value": "nicht_ok",
                    "title_template": "Hygiene-Massnahme: {kontrollpunkt}",
                    "description_template": "{massnahme}",
                    "assigned_to_field_key": "verantwortlich",
                    "due_at_field_key": "frist",
                    "priority": "high",
                }
            ],
        },
    },
    {
        "key": "reinigungsplan",
        "version": 1,
        "title": "Reinigungsplan",
        "category": "Betrieb",
        "description": "Dokumentation geplanter und erledigter Reinigungsarbeiten.",
        "tags": ["reinigung", "plan", "routine"],
        "definition": {
            "form": {"key": "reinigungsplan", "title": "Reinigungsplan"},
            "sections": [
                {"key": "basis", "title": "Basisdaten", "position": 1, "fields": [
                    field("datum", "Datum", "date", required=True),
                    field("bereich", "Bereich", required=True),
                    field("schicht", "Schicht"),
                ]}
            ],
            "repeatable_groups": [{"key": "aufgaben", "title": "Reinigungsaufgaben", "position": 2, "columns": [
                field("aufgabe", "Aufgabe", "text", required=True),
                field("erledigt", "Erledigt", "boolean"),
                field("uhrzeit", "Uhrzeit", "text"),
                field("bemerkung", "Bemerkung", "textarea"),
            ]}],
        },
    },
    {
        "key": "maengelmeldung",
        "version": 1,
        "title": "Maengelbehebung / Maengelmeldung",
        "category": "Instandhaltung",
        "description": "Meldung eines Mangels mit Prioritaet, Ort und Frist.",
        "tags": ["mangel", "instandhaltung"],
        "definition": {"form": {"key": "maengelmeldung", "title": "Maengelmeldung"}, "fields": [
            field("datum", "Datum", "date", required=True), field("ort", "Ort", required=True),
            select("prioritaet", "Prioritaet", [("normal", "Normal"), ("hoch", "Hoch"), ("kritisch", "Kritisch")], required=True),
            field("beschreibung", "Beschreibung", "textarea", required=True), field("frist", "Gewuenschte Frist", "date"),
        ], "action_item_rules": [{"name": "Mangel erzeugt Massnahme", "source_field_key": "beschreibung", "operator": "is_not_empty", "title_template": "Mangel: {ort}", "description_template": "{beschreibung}", "due_at_field_key": "frist", "priority": "normal"}]},
    },
    {
        "key": "schluesseluebergabe",
        "version": 1,
        "title": "Schluesseluebergabe",
        "category": "Bewohnerverwaltung",
        "description": "Protokoll fuer Ausgabe oder Ruecknahme von Schluesseln.",
        "tags": ["schluessel", "uebergabe"],
        "definition": {"form": {"key": "schluesseluebergabe", "title": "Schluesseluebergabe"}, "fields": [
            field("datum", "Datum", "date", required=True), field("bewohner_name", "Bewohner/in", required=True),
            select("vorgang", "Vorgang", [("ausgabe", "Ausgabe"), ("ruecknahme", "Ruecknahme")], required=True),
            field("schluesselnummer", "Schluesselnummer", required=True), field("unterschrift", "Unterschrift", "signature", required=True),
        ]},
    },
    {
        "key": "brandschutzkontrolle",
        "version": 1,
        "title": "Brandschutzkontrolle",
        "category": "Sicherheit",
        "description": "Regelmaessige Kontrolle von Fluchtwegen, Feuerloeschern und Meldern.",
        "tags": ["brandschutz", "sicherheit"],
        "definition": {"form": {"key": "brandschutzkontrolle", "title": "Brandschutzkontrolle"}, "fields": [
            field("datum", "Datum", "date", required=True), field("bereich", "Bereich", required=True),
            select("fluchtwege", "Fluchtwege frei", [("ja", "Ja"), ("nein", "Nein")], required=True),
            select("loescher", "Feuerloescher sichtbar/erreichbar", [("ja", "Ja"), ("nein", "Nein")], required=True),
            field("bemerkung", "Bemerkung", "textarea"), field("frist", "Frist bei Mangel", "date"),
        ], "action_item_rules": [{"name": "Brandschutzmangel", "source_field_key": "fluchtwege", "operator": "equals", "value": "nein", "title_template": "Brandschutz: Fluchtweg pruefen", "description_template": "{bemerkung}", "due_at_field_key": "frist", "priority": "critical"}]},
    },
    {
        "key": "besucherprotokoll",
        "version": 1,
        "title": "Besucherprotokoll",
        "category": "Dokumentation",
        "description": "Neutrales Besucherprotokoll fuer Empfang und Dokumentation.",
        "tags": ["besuch", "protokoll"],
        "definition": {"form": {"key": "besucherprotokoll", "title": "Besucherprotokoll"}, "fields": [
            field("datum", "Datum", "date", required=True), field("besucher_name", "Besucher/in", required=True),
            field("besuchte_person", "Besuchte Person / Bereich"), field("ankunft", "Ankunft"), field("ende", "Ende"), field("bemerkung", "Bemerkung", "textarea"),
        ]},
    },
    {
        "key": "bewohneraufnahme-checkliste",
        "version": 1,
        "title": "Bewohneraufnahme Checkliste",
        "category": "Bewohnerverwaltung",
        "description": "Administrative Checkliste fuer Aufnahmeprozesse ohne medizinische Bewertung.",
        "tags": ["aufnahme", "checkliste"],
        "definition": {"form": {"key": "bewohneraufnahme-checkliste", "title": "Bewohneraufnahme Checkliste"}, "fields": [
            field("bewohner_name", "Bewohner/in", required=True), field("aufnahmedatum", "Aufnahmedatum", "date", required=True),
            field("zimmer", "Zimmer"), field("unterlagen_vollstaendig", "Unterlagen vollstaendig", "boolean"),
            field("hausordnung_ausgehaendigt", "Hausordnung ausgehaendigt", "boolean"), field("bemerkung", "Bemerkung", "textarea"),
        ]},
    },
    {
        "key": "datenschutz-einwilligung-tracking",
        "version": 1,
        "title": "Datenschutz-Einwilligung Tracking",
        "category": "Datenschutz",
        "description": "Trackingformular fuer Dokumentationsstatus von Datenschutz-Einwilligungen.",
        "tags": ["datenschutz", "einwilligung", "dsgvo"],
        "definition": {"form": {"key": "datenschutz-einwilligung-tracking", "title": "Datenschutz-Einwilligung Tracking"}, "fields": [
            field("bewohner_name", "Bewohner/in", required=True), field("datum", "Datum", "date", required=True),
            select("status", "Status", [("liegt_vor", "liegt vor"), ("fehlt", "fehlt"), ("widerrufen", "widerrufen")], required=True),
            field("bemerkung", "Bemerkung", "textarea"),
        ]},
    },
]
