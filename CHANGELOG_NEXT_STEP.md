# Bewohnerformular - Professional Next Step

## Changed

- Rebuilt `entry_create.html`, `entry_edit.html`, and `entry_detail.html` to use the main `base/app_base.html` layout.
- Added professional entry summary cards, form panels, workflow strip, responsive form table styling, and review action blocks.
- Added explicit review/send permissions:
  - `can_review_entries`
  - `can_send_entries`
- Added status transition services:
  - `approve_entry_for_sending`
  - `reject_entry_for_correction`
  - `queue_entry_for_delivery`
- Added audit log records for approval, rejection, and queueing.
- Added URL routes and views for:
  - approval
  - rejection
  - moving approved entries into the outbox
- Extended `app.css` with entry workflow styling.

## Important production notes

- This step does not yet generate PDFs. The next professional step should add private PDF preview/rendering with WeasyPrint.
- The outbox queue action requires at least one active default `FormRecipient` for the selected form.
- Email sending itself is still intentionally not executed here. The next backend step should add a worker process using Celery/Redis and later SMTP or Microsoft Graph.
- PDF files must later be stored in private storage and served only through permission-checked Django views.
