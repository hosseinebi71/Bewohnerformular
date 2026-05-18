# Government Collective Workflow Update

This build adds the "Sammelliste" logic for forms such as Sozialticket:

- New Sozialticket entries stay in one open collective PDF table until they are sent.
- After successful send, the sent entries are marked archived and disappear from the open collective list.
- The next new entries automatically start the next open collective list.
- `Ausgangskorb` now shows both the administrative open dispatch groups and the technical outbox queue.
- PDF rendering uses ReportLab, not WeasyPrint, to avoid GTK/Pango issues on Windows.

Recommended local commands:

```powershell
python -m pip install -r requirements.txt
python manage.py check
python manage.py migrate
python manage.py seed_government_demo_forms
python manage.py runserver
```

Open `http://127.0.0.1:8000/formulare/`.
