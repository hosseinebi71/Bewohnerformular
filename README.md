# Bewohnerformular

Django application for resident-related government form workflows with live PDF previews, review/approval, collective dispatch lists, scheduling and audit-friendly archive handling.

## What is included

- Corporate sidebar/navigation with tablet/mobile off-canvas menu
- Search, filter and sorting controls on operational lists
- Dynamic form definitions and resident-linked entries
- Direct form entry without selecting a pre-existing resident
- Live PDF previews powered by ReportLab for Windows-friendly local development
- Collective dispatch logic for recurring forms, for example Sozialticket daily 05:00
- Draft, review, approval, outbox, sent and archive states
- Demo seed command for Sozialticket Antrag, ZAP Termin and Leistungsbescheid

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_government_demo_forms
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

## Useful commands

```bash
python manage.py check
python manage.py seed_government_demo_forms
python manage.py process_schedules --limit-per-schedule 100
python manage.py process_outbox --limit 20
```

## Notes

- `Sozialticket Antrag` is treated as a collective working list until dispatch.
- Sent items are archived through the outbox processing flow.
- Generated PDFs and local runtime files are private and ignored by Git.
