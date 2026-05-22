# Prompt 10.1-10.3 changed files

This package contains complete files for:

- Mobile/tablet usability improvements for form filling.
- Browser local draft protection using localStorage, scoped per form/entry and cleared on save/submit.
- QR code contexts that open a published form with optional resident/location/asset context.

## Files

```text
form_builder/apps.py
form_builder/qr_context_models.py
form_builder/qr_context_services.py
form_builder/qr_context_forms.py
form_builder/qr_context_views.py
form_builder/urls.py
form_builder/migrations/0017_qr_contexts.py
form_builder/tests/test_qr_contexts.py
templates/form_builder/base.html
templates/form_builder/entry_create.html
templates/form_builder/entry_edit.html
templates/form_builder/qr/context_list.html
templates/form_builder/qr/context_form.html
templates/form_builder/qr/context_detail.html
static/form_builder/mobile_forms.css
static/form_builder/local_draft.js
```

## Verify locally

```powershell
poetry run python manage.py migrate
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```

## Notes

- QR tokens are opaque random strings and do not expose raw database IDs.
- Local browser drafts exclude password, hidden, file inputs and CSRF values.
- Local drafts expire after 24 hours by default and are scoped per create/edit form.
- No dependency changes are required because `qrcode` already exists in pyproject.
