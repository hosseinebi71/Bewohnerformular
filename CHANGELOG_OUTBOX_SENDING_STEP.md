# Outbox sending step

This step adds the first professional sending pipeline for the Bewohner form workflow.

## Added

- `form_builder/mail_services.py`
  - Builds email messages from `OutboxItem`
  - Attaches the private generated PDF
  - Sends via Django's configured email backend
  - Marks successful items as `sent`
  - Creates `SentFormArchive` records automatically
  - Writes `AuditLog` records for successful and failed sending
  - Stores failure reason and retry metadata on `OutboxItem`

- `form_builder/management/commands/process_outbox.py`
  - Allows processing due outbox items from the terminal:

    ```powershell
    python manage.py process_outbox --limit 20
    ```

- Outbox UI action
  - Adds a protected button on `/formulare/ausgangskorb/`
  - Users with send permission can process due pending outbox items from the web UI

- Development-safe email configuration
  - `EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"`
  - Emails are printed to the terminal during local development
  - No real email is sent until SMTP or Microsoft Graph is configured

- Login/static fixes preserved
  - `LOGIN_REDIRECT_URL`
  - `/profile/` and `/accounts/profile/` redirects
  - `STATICFILES_DIRS`

## How to test locally

1. Ensure migrations are applied:

   ```powershell
   python manage.py makemigrations form_builder
   python manage.py migrate
   ```

2. Create or open an approved form entry.
3. Generate the PDF preview and store it privately.
4. Move the entry to the outbox.
5. Run:

   ```powershell
   python manage.py process_outbox --limit 20
   ```

6. Check the terminal output. With the console email backend, the email is printed instead of really sent.
7. Open `/formulare/versandt/` and `/formulare/archiv/` to verify sent and archived records.

## Production note

For real company sending, switch the email backend to SMTP or Microsoft Graph only after the full PDF, permission, audit, and private storage workflow has been tested.
