# Corporate v8 - Formularvorlagen aus Papiermustern

Diese Version ergänzt die vorhandenen Abläufe um weitere behördliche Formularvorlagen mit sauberer PDF-Ausgabe per ReportLab.

## Neue Formularvorlagen

- Freiwillige Rückkehr
- BZR wöchentliche Sprechstunde
- AB Sprechstundenliste
- Beschwerdebogen ZUE-Weeze II

## Überarbeitet

- Leistungsbescheid wird jetzt als offene Sammelliste im Tabellenlayout ausgegeben.
- Alte, nicht mehr passende Formularfelder werden beim Seed sauber deaktiviert und aus der aktiven Formularstruktur entfernt.
- Tabellenformulare sammeln offene Einträge bis zum Versand, ähnlich wie Sozialticket.
- Beschwerdebogen hat ein eigenes PDF-Layout mit Kategorien, Freitextfeld und Unterschriftszeilen.

## Test

Ausgeführt:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py seed_government_demo_forms
```
