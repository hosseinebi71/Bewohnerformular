# Prompt 3-1 / 3-2 changed files

Implements repeatable dynamic tables/groups for Bewohnerformular.

## What changed

- Adds `RepeatableGroup` and `RepeatableGroupColumn` models.
- Adds server-side parsing and validation for row arrays stored in `FormEntry.data[group_key]`.
- Adds server-rendered builder UI for repeatable tables and columns.
- Adds entry rendering with add/remove rows before submit.
- Adds mobile-friendly file/photo columns using `accept="image/*"` and `capture="environment"` defaults.
- Adds repeatable table display in entry detail and PDF row generation via runtime integration.

## Files

Copy these files into the project root, preserving paths.

## Commands

```powershell
poetry run python manage.py migrate
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```

## Notes

This intentionally avoids rewriting the existing monolithic `models.py` and builds on the extension-module pattern already used for attachments.
