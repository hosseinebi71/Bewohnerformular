# Security Patch Notes

Implemented in this patched package:

- Production settings now fail closed when `DJANGO_DEBUG=False` and required secrets/hosts/email backend are not configured.
- Secure cookie, SSL redirect, HSTS, content-type nosniff and clickjacking defaults are enabled for production-like deployments.
- Object-level access checks were added for form entries, PDF documents, outbox items and archive records.
- Operational list selectors now scope normal users to entries they created, updated or locked; staff/admin still see all work items.
- PDF preview/download endpoints no longer return raw exception text to users; details go to server logs.
- PDF downloads now check object-level document permission before opening the private file.
- Outbox processing now uses `select_for_update()` and `skip_locked` where the database supports it to reduce double-send risk.
- Regression tests were expanded from 3 to 6 tests, covering owner/staff/other-viewer access and PDF permission inheritance.

Validated with:

```bash
DJANGO_DEBUG=1 python manage.py check
DJANGO_DEBUG=1 python manage.py test
DJANGO_ENVIRONMENT=production DJANGO_DEBUG=0 DJANGO_SECRET_KEY=testsecret DJANGO_ALLOWED_HOSTS=example.com EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend python manage.py check
```
