# Bewohnerformular Prompt 12.1, 12.2, 13.1, 13.2

This ZIP contains complete changed/new files, not patches.

## Scope

- Reusable form template library.
- Professional German starter templates.
- Idempotent seed command.
- High-value final regression tests around routing, permission scope, attachment access and template copying.
- Final quality-oriented code cleanup for the new template library.

## Files

- `form_builder/apps.py`
- `form_builder/form_template_models.py`
- `form_builder/form_template_services.py`
- `form_builder/form_template_forms.py`
- `form_builder/form_template_views.py`
- `form_builder/starter_template_data.py`
- `form_builder/urls.py`
- `form_builder/migrations/0018_form_templates.py`
- `form_builder/management/commands/seed_starter_templates.py`
- `form_builder/tests/test_form_template_library.py`
- `form_builder/tests/test_final_regression.py`
- `templates/form_builder/form_templates/list.html`
- `templates/form_builder/form_templates/detail.html`
- `templates/form_builder/form_templates/form.html`

## Local verification

```powershell
cd C:\Users\hosse\Bewohnerformular
poetry run python manage.py migrate
poetry run python manage.py seed_starter_templates
poetry run python manage.py seed_starter_templates
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pytest
poetry run pre-commit run --all-files
```

The seed command is intentionally idempotent. Running it twice should not create duplicates.
