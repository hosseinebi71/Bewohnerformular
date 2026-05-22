# Prompt 2-1 / 2-2 / 2-3 corrected changed files

This ZIP fixes the local integration problems from the previous ZIP:

1. The migration is now `form_builder/migrations/0010_form_entry_attachments.py` and depends on your existing latest migration:
   `0009_rename_form_builde_section_7406d6_idx_form_builde_section_adedc7_idx_and_more`.
2. Tests now live in `form_builder/tests/test_attachments.py` instead of `form_builder/tests.py`, so they do not conflict with the existing `form_builder/tests/` package.

Before copying this ZIP over the project, remove the two files created by the previous ZIP if they exist:

```powershell
Remove-Item .\form_builder\migrations\0002_form_entry_attachments.py -Force -ErrorAction SilentlyContinue
Remove-Item .\form_builder\tests.py -Force -ErrorAction SilentlyContinue
```

Then copy the folders from this ZIP into the project root and run:

```powershell
poetry run python manage.py migrate
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```
