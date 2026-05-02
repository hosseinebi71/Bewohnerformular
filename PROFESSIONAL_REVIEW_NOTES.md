# Professional review notes

Diese Version enthaelt die nachtraeglich gebuendelten Verbesserungen fuer UI, mobile Nutzung und zentrale Backend-Workflows.

## UI / CSS
- Tabellenbasierte Entry-Formulare wurden durch ein gemeinsames Feld-Partial und ein responsives Grid ersetzt.
- Pflichtfelder, Checkboxen, Hilfetexte, Fehler und Fokus-Zustaende sind jetzt konsistenter dargestellt.
- Mobile Tabellen wechseln in eine kartenartige Darstellung, sofern die Zellen `data-label` enthalten.
- Schedule-Formulare nutzen dieselbe Feldlogik wie Entry-Formulare.

## Backend
- Due-Schedules beachten `start_at` und `end_at` im Queryset.
- Nach Schedule-Ausfuehrung wird die naechste Ausfuehrung gegen das Enddatum validiert; abgelaufene Schedules werden retired.
- Outbox-Verarbeitung behaelt die berechnete Prioritaetsreihenfolge nach dem Query stabil bei.
- PDF-Downloads werden im AuditLog protokolliert.

## Lokaler Start
```bash
cp .env.example .env
./scripts/bootstrap_local.sh
. .venv/bin/activate
python manage.py runserver
```

Hinweis: In der ChatGPT-Sandbox konnte Django/WeasyPrint nicht nachinstalliert werden, weil externe Paketdownloads nicht verfuegbar waren. Syntax- und Laufzeittests sollten lokal nach `pip install -r requirements.txt` ausgefuehrt werden.
