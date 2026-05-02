# Bewohnerformular

Django application for a professional resident form workflow. It supports dynamic form definitions, resident-linked form entries, review/approval steps, PDF generation, outbox processing, scheduling, and an audit-friendly archive flow.

## Features

- Dynamic form builder models with versioned published forms
- Draft, review, approval, rejection, ready-to-send, sent, and archive states
- Role-aware navigation and permissions for Admin, Staff, and Viewer groups
- Private PDF generation and protected download flow
- Outbox queue with console email backend for local development
- Schedule management for recurring/form-driven outbox preparation
- Demo seed command for local testing

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

Demo login after running the seed command:

```text
Username: demo.admin
Password: ChangeMe!12345
```

## Useful commands

```bash
python manage.py process_schedules --limit-per-schedule 100
python manage.py process_outbox --limit 20
python manage.py check
```

## Security notes

- `db.sqlite3`, generated PDFs, `private_documents/`, `.env`, and other runtime artifacts are intentionally ignored.
- Keep production secrets in environment variables.
- Do not serve `PRIVATE_DOCUMENT_ROOT` as public static/media content.
