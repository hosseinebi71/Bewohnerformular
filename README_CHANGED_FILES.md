# Prompt 11.1 / 11.2 / 11.3

Included:

- audit_services.py: structured audit helpers preserving the existing hash chain.
- retention_services.py: dry-run-first retention policy processor.
- management command apply_retention_policy.
- permissions.py: shared permission helpers for exports, imports, templates, attachments, action items and retention operations.
- reporting_views.py: hardened export/report permissions plus audit events.
- tests/test_audit_retention_permissions.py: regression tests for audit, retention and export permission helpers.

Local verification:

```powershell
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
poetry run python manage.py apply_retention_policy --dry-run
```

Retention safety:

- Default command mode is dry-run unless `--apply` is provided.
- Apply mode anonymizes FormEntry.data and flags archive metadata.
- It does not delete database rows or physical files.
- Every processed record creates an append-only AuditLog row.
