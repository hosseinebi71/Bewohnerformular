# Prompt 6-1 / 6-2 / 6-3 changed files

This ZIP contains full replacement/new files, not a patch.

## Feature scope

- Upload original PDF templates for an existing dynamic form.
- Store source PDFs separately from generated `PDFDocument` output.
- Analyze page count and page sizes with `pypdf`.
- Create manual field placements with normalized coordinates: `x`, `y`, `width`, `height` in the `0..1` range. The coordinate origin is the top-left corner of the PDF page.
- Validate page number, coordinate bounds, and field/template form consistency.
- Fill final PDFs by preserving the original PDF pages as background and drawing dynamic values over them.
- Render text/date/checkbox/signature placements.
- Keep the existing ReportLab generic renderer as fallback when no active template exists.

## Files

- `pyproject.toml`
- `form_builder/apps.py`
- `form_builder/pdf_template_models.py`
- `form_builder/pdf_template_services.py`
- `form_builder/pdf_template_forms.py`
- `form_builder/pdf_template_views.py`
- `form_builder/urls.py`
- `form_builder/migrations/0014_pdf_templates.py`
- `form_builder/tests/test_pdf_templates.py`
- `templates/form_builder/pdf_templates/list.html`
- `templates/form_builder/pdf_templates/upload.html`
- `templates/form_builder/pdf_templates/detail.html`
- `templates/form_builder/pdf_templates/placement_form.html`

## Local commands

```powershell
cd C:\Users\hosse\Bewohnerformular
poetry add pypdf@^5.1.0
poetry run python manage.py migrate
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```

If `ruff format` modifies files, run pre-commit once more.
