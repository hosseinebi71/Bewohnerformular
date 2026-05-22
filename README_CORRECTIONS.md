# Prompt 12/13 final import correction 2

This fixes the remaining audit helper name mismatch in `form_template_services.py`.

The project audit service exposes `audit_event`, not `log_audit_event`.
Copy both files over the project root and rerun:

```powershell
poetry run python manage.py check
poetry run python manage.py migrate
poetry run python manage.py seed_starter_templates
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```
