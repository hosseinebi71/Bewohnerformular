# Demo Seed Command

This patch adds a professional local setup command for fast testing.

## Files

```text
form_builder/management/commands/seed_demo_data.py
form_builder/schedule_services.py
```

`schedule_services.py` also contains the fixed `Q` import.

## Run

```powershell
python manage.py makemigrations form_builder
python manage.py migrate
python manage.py seed_demo_data
python manage.py process_schedules --limit-per-schedule 100
python manage.py process_outbox --limit 20
python manage.py runserver
```

## Demo login

```text
Username: demo.admin
Password: ChangeMe!12345
```

Use this user only locally.

## Test pages

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/formulare/
http://127.0.0.1:8000/formulare/ausgangskorb/
http://127.0.0.1:8000/formulare/versandt/
http://127.0.0.1:8000/formulare/archiv/
http://127.0.0.1:8000/einstellungen/zeitplaene/
```

The command creates groups, a local demo admin, a Bewohner, a published form, fields, recipient, due schedule, approved entry, and private demo PDF.
