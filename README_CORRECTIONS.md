# Corrections after Prompt 4 local test

This ZIP fixes the concrete failures from the local run:

1. `config/settings.py`
   - Adds `STORAGES["default"]` with a private FileSystemStorage location.
   - Keeps the existing staticfiles storage behavior.
   - This fixes `InvalidStorageError: Could not find config for 'default' in settings.STORAGES` during attachment/signature tests.

2. `form_builder/urls.py`
   - Merges the repeatable table routes and the conditional rule routes into one URL config.
   - This fixes `NoReverseMatch: repeatable_group_create` after the Prompt 4 ZIP overwrote the Prompt 3 URL config.

3. `form_builder/repeatable_entry_views.py`
   - Uses the repeatable-aware entry views as the active entry views.
   - Adds conditional server-side validation to create/save/validate/review flows.
   - Keeps repeatable table parsing and attachments active.

4. `form_builder/tests/test_repeatable_groups.py`
   - Imports `ValidationError` and asserts that exact exception instead of broad `Exception`.
   - This fixes ruff/flake8 F821 and B017.

Run:

```powershell
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```

If pre-commit reformats files, run it once more.
