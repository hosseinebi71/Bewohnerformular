# Bewohnerformular builder/import UI hotfix

Apply by copying these files over your local repository root.

After extracting, run:

```powershell
poetry run python manage.py check
poetry run python manage.py makemigrations --check --dry-run
poetry run pytest form_builder/tests/test_form_builder_ui.py form_builder/tests/test_final_regression.py form_builder/tests/test_excel_import.py form_builder/tests/test_pdf_templates.py form_builder/tests/test_docx_templates.py
poetry run ruff check .
poetry run black --check .
poetry run isort --check-only .
```

If `private_media/` is tracked in your local git status, remove generated test uploads from git tracking once:

```powershell
git rm -r --cached private_media
```

Keep the real files on disk if needed; they should not be committed.
