# Corporate v7

## UI/UX

- Sidebar deutlich ruhiger und heller abgestimmt.
- Aktiver Navigationspunkt nutzt nur noch eine schmale linke Markierung; kein schwerer Hintergrund mehr.
- Schnellzugriff/Search im Sidebar-Kopf entfernt.
- Desktop-Sidebar kann eingeklappt werden; Status wird im Browser gespeichert.
- Mobile und Tablet behalten Off-Canvas Navigation.
- Buttons und Topbar-Pills optisch vereinheitlicht.
- Root-Templates und App-Templates sind synchronisiert, damit Django nicht alte Templates aus `BASE_DIR/templates` rendert.
- Root-Static und App-Static sind synchronisiert, damit `form_builder/app.css` sicher die neue UI laedt.

## E-Mail / Zeitplan / Formular

- `FormSchedule.recipients` als echte Many-to-Many-Verbindung zu `FormRecipient` ergänzt.
- Migration `0003_formschedule_recipients` uebernimmt bestehende `recipient_ids` aus `config`.
- Zeitplan-Formular speichert die E-Mail-Ziele sichtbar und konsistent.
- Zeitplan-Liste zeigt verknuepfte E-Mail-Ziele direkt an.
- Admin `Formular-E-Mail-Ziele` synchronisiert automatische Zeitplaene beim Speichern.
- Admin `Formularzeitplaene` zeigt und bearbeitet die verknuepften E-Mail-Ziele.
- Seed-Befehl verknuepft Sozialticket und ZAP direkt mit ihren Empfaengern und Zeitplaenen.

## Geprueft

- `python manage.py check`
- `python manage.py migrate`
- `python manage.py seed_government_demo_forms`
- Django Test-Client: Dashboard, Zeitplaene und Admin FormRecipient laden mit Status 200.
