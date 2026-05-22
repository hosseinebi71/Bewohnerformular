# Prompt 5-1 bis 5-5 - Excel import foundation

## Inhalt

- Excel upload/import job models
- Deterministic openpyxl workbook analysis
- Mapping UI for sheet/form conversion
- Draft form generation into existing Form/FormSection/Field architecture
- RepeatableGroup generation for detected tables
- Hygiene Kontrolle synthetic workbook tests and required-if metadata for Nicht OK rows

## Wichtig

`openpyxl` wurde als Poetry dependency in `pyproject.toml` ergänzt. Wenn dein lokales Lockfile noch nicht aktualisiert ist, einmal ausführen:

```powershell
poetry add openpyxl@^3.1.5
```

Danach:

```powershell
poetry run python manage.py migrate
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```

## Neue URLs

- `/einstellungen/excel-importe/`
- `/einstellungen/excel-importe/hochladen/`
- `/einstellungen/excel-importe/<job_id>/`
- `/einstellungen/excel-importe/<job_id>/mapping/`
- `/einstellungen/excel-importe/<job_id>/generieren/`
