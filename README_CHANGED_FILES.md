# Prompt 7.1 + 7.2 - DOCX templates

This package adds DOCX template upload, placeholder extraction and DOCX generation from FormEntry data.

## Files

- pyproject.toml
- form_builder/apps.py
- form_builder/docx_template_models.py
- form_builder/docx_template_services.py
- form_builder/docx_template_forms.py
- form_builder/docx_template_views.py
- form_builder/urls.py
- form_builder/migrations/0015_docx_templates.py
- form_builder/tests/test_docx_templates.py
- templates/form_builder/docx_templates/list.html
- templates/form_builder/docx_templates/upload.html
- templates/form_builder/docx_templates/detail.html

## Local commands

```powershell
poetry add python-docx@^1.1.2
poetry run python manage.py migrate
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```

## Notes

- Only `.docx` is accepted.
- `.doc`, `.docm` and macro-enabled files are rejected.
- Placeholders use `{{field_key}}`, plus metadata keys like `{{bewohner_name}}`, `{{datum}}`, `{{form_title}}`.
- Generated DOCX files are stored through the existing private `PDFDocument` output architecture with a DOCX content type.
