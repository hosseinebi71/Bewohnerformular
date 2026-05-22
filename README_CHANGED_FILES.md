# Bewohnerformular Prompt 8.1-8.3 changed files

Implements ActionItem / Massnahme management, automatic ActionItem creation from form submissions, and reminder/escalation foundation.

## Apply
Copy these files into the project root, preserving paths.

## Verify

```powershell
cd C:\Users\hosse\Bewohnerformular
poetry run python manage.py migrate
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
poetry run python manage.py process_reminders --due-soon-days 2 --escalate-after-days 3
```

## Notes

- ActionItem generation is idempotent via `(source_entry, source_rule_key, source_row_key, source_field_key)`.
- Closed tasks are not overwritten by later saves.
- Reminder generation creates deduplicated ReminderLog rows and AuditLog entries; it does not send email in tests.
- Submission integration happens in the entry review flow after repeatable table payload is saved.
