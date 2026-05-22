# Bewohnerformular Prompt 2-1 / 2-2 / 2-3 changed files

Copy these files into the root of `C:\Users\hosse\Bewohnerformular`, preserving folders.

## Implemented

- Real secure dynamic form file fields using `FormEntryAttachment`.
- Private/protected attachment download through Django view permission checks.
- Server-side upload validation for file size and allowed content types.
- SHA-256 hashing, content type, size, uploader, timestamp and audit metadata.
- Mobile-friendly photo capture attributes for file fields (`accept`, optional `capture`).
- Existing attachment list on edit/detail pages with thumbnails for images.
- Replace/remove attachments while entry remains editable (`draft` / `rejected`).
- Prevent attachment mutation after review/approval by service and delete-view guards.
- Auditable signature storage as protected PNG attachment with signer, timestamp and hash.
- Signature field values render safely in detail/PDF as signed audit text; the signature image is available in the attachment list/download.
- Tests for upload metadata, invalid content type, signature storage, locked submit flow and unauthorized download.

## Files changed/added

```text
form_builder/apps.py
form_builder/attachment_models.py
form_builder/attachment_entry_views.py
form_builder/attachment_views.py
form_builder/migrations/0002_form_entry_attachments.py
form_builder/services.py
form_builder/tests.py
form_builder/urls.py
templates/form_builder/entry_create.html
templates/form_builder/entry_edit.html
templates/form_builder/entry_detail.html
templates/form_builder/partials/entry_attachment_list.html
```

## Run locally

```powershell
cd C:\Users\hosse\Bewohnerformular
python manage.py migrate
python manage.py check
python manage.py test form_builder
```

If you use Poetry:

```powershell
poetry run python manage.py migrate
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```

## Notes

- The implementation keeps existing non-file dynamic forms compatible.
- File uploads are stored by Django's configured file storage under a non-public `private/...` path and are served only through permission-checked views.
- For production, keep media/private upload directories away from public static serving.
