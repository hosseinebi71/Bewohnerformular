# Prompt 5 corrections after local test run

Fixes:

1. Excel generation no longer reuses `Field.position` from 1 for every sheet in a combined form. `Field.position` is unique per form in the existing model, so generated fields now continue from the current highest position.
2. Excel-generated repeatable group keys are made unique per form.
3. `test_conditional_rules.py` now imports `ValidationError` and asserts that specific exception instead of broad `Exception`, satisfying Ruff B017.

Copy these files over the project root and rerun:

```powershell
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```
