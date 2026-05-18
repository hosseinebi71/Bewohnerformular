# Security Next Step Patch

## Inhalt

- AuditLog ist jetzt manipulations-erkennbar:
  - `previous_hash` und `entry_hash` bilden eine SHA-256 Hash-Kette.
  - AuditLog ist append-only und kann nach dem Erstellen nicht mehr gespeichert/geaendert werden.
  - Migration `0006_audit_hash_chain` backfilled bestehende Audit-Eintraege.
- Neues Kommando: `python manage.py verify_audit_log`
  - Prueft die Audit-Hash-Kette und bricht mit Exit-Code 1 bei Abweichungen ab.
- Neues Kommando: `python manage.py purge_expired_archives`
  - Dry-run per Default.
  - Mit `--confirm --delete-files` werden abgelaufene Archivdatensaetze, orphan PDF-Datensaetze und private PDF-Dateien geloescht.
- Recent activity und AuditLog-Listen sind fuer normale Benutzer staerker objektbezogen gefiltert.
- Zusaetzliche Tests fuer:
  - Audit hash chain und append-only Verhalten
  - Entry/PDF Object-Level-Zugriff via Views
  - Outbox due selection und send/archive flow
  - Retention dry-run und confirm-delete
  - Schedule daily/weekly/manual calculation
  - Selector scoping fuer sent/archive/recent activity

## Validierung

Ausgefuehrt:

```bash
DJANGO_DEBUG=1 python manage.py test -v 2
DJANGO_DEBUG=1 python manage.py check
DJANGO_ENVIRONMENT=production DJANGO_DEBUG=0 DJANGO_SECRET_KEY=testsecret DJANGO_ALLOWED_HOSTS=example.com EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend python manage.py check
DJANGO_DEBUG=1 python manage.py verify_audit_log
```

Ergebnis:

- 27 Tests OK
- Development system check OK
- Production-like system check OK
- AuditLog verification OK

## Wichtiger Deploy-Hinweis

Nach dem Einspielen unbedingt migrieren:

```bash
python manage.py migrate
python manage.py verify_audit_log
```

`purge_expired_archives` sollte zuerst ohne Flags laufen. Erst danach mit `--confirm --delete-files` in einem kontrollierten Betriebsfenster ausfuehren.
