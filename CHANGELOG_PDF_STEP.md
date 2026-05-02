# Professional PDF Preview Step

This package continues from `bewohner_professional_next_step` and adds a secure PDF preparation layer before any email delivery is implemented.

## Added

- Private document settings:
  - `PRIVATE_DOCUMENT_ROOT`
  - `PDF_COMPANY_NAME`
- `form_builder/pdf_services.py`
  - PDF HTML rendering
  - WeasyPrint PDF generation
  - SHA-256 hashing
  - private filesystem storage
  - `PDFDocument` creation
  - PDF render audit log
- PDF templates:
  - `templates/form_builder/pdf/form_entry_pdf.html`
  - `templates/form_builder/pdf_preview.html`
- Secure routes:
  - PDF preview per `FormEntry`
  - private PDF generation
  - permission-checked PDF download
- Entry detail now links to PDF preview and the latest generated PDF.
- Outbox queueing now requires a generated PDF and attaches it to `OutboxItem`.
- Added `requirements.txt` with Django, WeasyPrint and PostgreSQL driver.

## Important

PDF files are stored below `PRIVATE_DOCUMENT_ROOT`. This folder must never be served as static/media/public content. Downloads go through Django permission checks.

## Next recommended production step

Add email delivery backends and worker infrastructure:

- `email_backends.py` for SMTP / Microsoft Graph abstraction
- Celery + Redis for retry-safe outbox processing
- Delivery audit logs
- Archive creation after successful delivery
