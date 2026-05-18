# Corporate v11 - Meldung Besonderes Vorkommnis (BV)

- Added form `Meldung Besonderes Vorkommnis (BV)`.
- Added official ReportLab PDF renderer for the BV form.
- Added exact selectable options for:
  - 5. Art des Vorfalls (3 adjacent selections)
  - 8. Einsatz von (3 adjacent selections)
  - 9. Wer wurde informiert (3 adjacent selections)
  - 10. Vorgang
- Added text fields for Date, Einrichtung, LfdNr., Meldender, Sonstiges, Zeitliche Abfolge, Sachverhalt, Täter, Geschädigte and Zeugen.
- Added a clean one-page official PDF output with light-blue input boxes, footer revision and clear section layout.
- Seed command remains idempotent and safe to run multiple times.

Tested:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py seed_government_demo_forms
```
