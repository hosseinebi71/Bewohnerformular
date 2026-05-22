# Prompt 11 retention correction

This correction fixes retention candidate discovery across SQLite/PostgreSQL.

## Problem

The original service used a nested JSON `exclude(archive_metadata__retention__status="processed")` filter. On SQLite, missing JSON paths can behave differently from PostgreSQL and caused due archive rows to be excluded in tests.

## Fix

The service now:

- filters due archives in SQL only by `retention_until <= as_of`,
- checks `archive_metadata.retention.status == "processed"` in Python,
- keeps dry-run write-free,
- preserves the same anonymization and audit behavior for `--apply`.

## Verify

```powershell
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
poetry run python manage.py apply_retention_policy --dry-run
```
