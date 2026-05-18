# Bewohnerformular v13 Bugfix / Hardening

## Behobene Bugs

- Dashboard: `in_review` wird wieder aus `get_entries_in_review_queryset()` berechnet und ist nicht mehr hart auf `0` gesetzt.
- Arbeitsliste/Entwürfe: normale Mitarbeiter sehen nur eigene offene Einträge; Admin/Staff sehen die gesamte Arbeitsliste.
- PDF-Service: `get_latest_generated_pdf_document()` hat wieder eine zentrale Quelle in `pdf_services.py`; `services.py` importiert diese Funktion nur noch.
- Versandgruppen: N+1-Abfrage bei Zeitplan-Labels reduziert; aktive Zeitpläne werden gesammelt geladen.

## Konfiguration / Betrieb

- Passwortvalidierung bleibt in lokaler Entwicklung deaktiviert, ist bei `DJANGO_DEBUG=False` aber automatisch aktiv.
- Datenbank kann per Environment auf PostgreSQL gestellt werden:
  - `DJANGO_DB_ENGINE=postgresql`
  - `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`
  - Ohne diese Einstellung bleibt SQLite für lokale Entwicklung aktiv.

## Tests

- Grundlegende Regressionstests für Dashboard-Zählung, Mitarbeiter-Sichtbarkeit und zentrale PDF-Helferfunktion ergänzt.
