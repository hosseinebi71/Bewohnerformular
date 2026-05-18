# Security Scope Step Notes

This patch adds organization/form-family scoped data access on top of the prior object-level controls.

## New data-scope fields

`UserAccessProfile` now has:

- `scope_mode`: `all`, `org_units`, or `own`
- `org_units`: JSON list of stable organization/facility/department codes
- `allowed_form_keys`: optional JSON list of form family keys

`Bewohner` and `Form` now have `org_unit` fields. These are indexed and used to scope FormEntry, PDFDocument, OutboxItem, SentFormArchive, dashboard counts, list views and recent activity.

## Default behavior

- Superusers/Admin group users keep unrestricted access.
- Legacy staff users without a `UserAccessProfile` keep unrestricted access for backward compatibility.
- Staff users with a profile can now be restricted to org units/form families.
- Normal users with no active profile keep own-entry access only.
- `scope_mode=org_units` requires at least one org unit; otherwise it matches no data.
- `allowed_form_keys` is an additional restriction whenever it is populated.

## Important deploy notes

1. Run migrations:

```bash
python manage.py migrate
```

2. Populate `org_unit` for existing `Bewohner` and `Form` records before turning on `scope_mode=org_units` broadly.

3. For staff who should remain global, either leave no `UserAccessProfile`, or set `scope_mode=all` and leave `allowed_form_keys=[]`.

4. For restricted staff/viewer accounts, create/update `UserAccessProfile` with explicit `org_units` and optional `allowed_form_keys`.

## Validation

This patch was validated with:

```bash
DJANGO_DEBUG=1 python manage.py test -v 1
DJANGO_DEBUG=1 python manage.py check
DJANGO_DEBUG=1 python manage.py makemigrations --check --dry-run
DJANGO_ENVIRONMENT=production DJANGO_DEBUG=0 DJANGO_SECRET_KEY=testsecret123 DJANGO_ALLOWED_HOSTS=example.com EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend python manage.py check
DJANGO_DEBUG=1 python manage.py migrate --noinput
DJANGO_DEBUG=1 python manage.py verify_audit_log
```

Test suite result: 48 tests, OK.
