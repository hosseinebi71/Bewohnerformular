# Prompt 8 corrections after local test

Fixes:

1. `ActionItem.due_at` date-only values are stored around local noon instead of midnight, avoiding Europe/Berlin -> UTC previous-day shifts.
2. `test_action_items.py` checks the local date via `timezone.localdate()`.
3. `test_pdf_templates.py` no longer compares PDF byte length, because pypdf/reportlab output can be smaller after overlay/optimization. It verifies a valid one-page PDF instead.

After copying these files, run:

```powershell
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
poetry run python manage.py makemigrations --check --dry-run
```

If `ruff-format` or `isort` modifies files, run pre-commit once more and then rerun the tests.
