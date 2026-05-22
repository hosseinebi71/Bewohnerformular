# Prompt 9.1 - 9.3 changed files

Implements:

- operational dashboard service and page
- permission-scoped Excel export for FormEntry data
- repeatable table export to separate workbook sheets
- monthly management PDF report
- audit log entries for export/report generation
- tests for workbook content, dashboard counts and PDF generation

Local verification:

```powershell
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```
