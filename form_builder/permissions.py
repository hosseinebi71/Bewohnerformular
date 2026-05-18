from django.db.models import Q

ADMIN_GROUP = "Admin"
STAFF_GROUP = "Staff"
VIEWER_GROUP = "Viewer"


def _is_authenticated(user) -> bool:
    return bool(user and user.is_authenticated)


def _has_group(user, group_name: str) -> bool:
    if not _is_authenticated(user):
        return False
    return user.groups.filter(name=group_name).exists()


def _access(user):
    if not _is_authenticated(user):
        return None
    try:
        profile = user.form_access_profile
    except Exception:
        return None
    return profile if profile.is_active else None


def _flag(user, name: str, default: bool) -> bool:
    if not _is_authenticated(user):
        return False
    if user.is_superuser:
        return True
    profile = _access(user)
    if profile is not None:
        return bool(getattr(profile, name, False))
    return default


def is_admin(user) -> bool:
    if not _is_authenticated(user):
        return False
    return bool(user.is_superuser or _has_group(user, ADMIN_GROUP))


def is_staff_user(user) -> bool:
    if not _is_authenticated(user):
        return False
    return bool(is_admin(user) or user.is_staff or _has_group(user, STAFF_GROUP))


def is_viewer(user) -> bool:
    if not _is_authenticated(user):
        return False
    return bool(_has_group(user, VIEWER_GROUP) and not is_admin(user) and not is_staff_user(user))


def can_view_dashboard(user) -> bool:
    default = bool(is_admin(user) or is_staff_user(user) or _has_group(user, VIEWER_GROUP))
    return _flag(user, "can_dashboard", default)


def can_view_forms(user) -> bool:
    default = can_view_dashboard(user)
    return _flag(user, "can_forms", default)


def can_create_entries(user) -> bool:
    default = bool(is_admin(user) or is_staff_user(user))
    return _flag(user, "can_create", default)


def can_review_entries(user) -> bool:
    return can_send_entries(user)


def can_send_entries(user) -> bool:
    default = bool(is_admin(user) or is_staff_user(user))
    return _flag(user, "can_send", default)


def can_view_settings(user) -> bool:
    default = bool(is_admin(user) or is_staff_user(user))
    return _flag(user, "can_settings", default)


def can_manage_settings(user) -> bool:
    default = is_admin(user)
    return _flag(user, "can_manage_settings", default)


def can_view_archive(user) -> bool:
    default = can_view_forms(user)
    return _flag(user, "can_archive", default)


def _list_from_profile(profile, attr: str) -> list[str]:
    values = getattr(profile, attr, []) if profile is not None else []
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _scope_mode(profile) -> str:
    return getattr(profile, "scope_mode", "own") if profile is not None else "own"


def _form_key_allowed(profile, form_key: str | None) -> bool:
    allowed = _list_from_profile(profile, "allowed_form_keys")
    if not allowed:
        return True
    return bool(form_key and form_key in allowed)


def _entry_form_key(entry) -> str | None:
    form = getattr(entry, "form", None)
    return getattr(form, "key", None) or getattr(entry, "form_key", None)


def _entry_org_units(entry) -> set[str]:
    values = set()
    form = getattr(entry, "form", None)
    bewohner = getattr(entry, "bewohner", None)
    for value in (getattr(form, "org_unit", ""), getattr(bewohner, "org_unit", "")):
        value = str(value or "").strip()
        if value:
            values.add(value)
    return values


def _is_owner_or_editor(user, obj) -> bool:
    if not _is_authenticated(user) or obj is None:
        return False
    user_id = getattr(user, "pk", None)
    return bool(
        user_id
        and (
            getattr(obj, "created_by_id", None) == user_id
            or getattr(obj, "updated_by_id", None) == user_id
            or getattr(obj, "locked_by_id", None) == user_id
        )
    )


def has_unrestricted_data_scope(user) -> bool:
    if not _is_authenticated(user):
        return False
    if is_admin(user):
        return True
    profile = _access(user)
    if profile is None:
        # Backwards-compatible default for legacy staff users without a profile.
        return bool(is_staff_user(user))
    return _scope_mode(profile) == "all" and not _list_from_profile(profile, "allowed_form_keys")


def _scope_allows_entry(user, entry) -> bool:
    if not _is_authenticated(user) or entry is None:
        return False
    if is_admin(user):
        return True
    profile = _access(user)
    if profile is None:
        return bool(is_staff_user(user) or _is_owner_or_editor(user, entry))

    if not _form_key_allowed(profile, _entry_form_key(entry)):
        return False

    mode = _scope_mode(profile)
    if mode == "all":
        return True
    if mode == "org_units":
        org_units = set(_list_from_profile(profile, "org_units"))
        return bool(org_units and _entry_org_units(entry).intersection(org_units))
    return _is_owner_or_editor(user, entry)


def entry_scope_q(user) -> Q:
    """Database filter matching can_view_entry for FormEntry querysets."""
    if not _is_authenticated(user):
        return Q(pk__isnull=True)
    if is_admin(user):
        return Q()
    profile = _access(user)
    if profile is None:
        if is_staff_user(user):
            return Q()
        return Q(created_by=user) | Q(updated_by=user) | Q(locked_by=user)

    q = Q()
    form_keys = _list_from_profile(profile, "allowed_form_keys")
    if form_keys:
        q &= Q(form__key__in=form_keys)

    mode = _scope_mode(profile)
    if mode == "all":
        return q
    if mode == "org_units":
        org_units = _list_from_profile(profile, "org_units")
        if not org_units:
            return Q(pk__isnull=True)
        return q & (Q(form__org_unit__in=org_units) | Q(bewohner__org_unit__in=org_units))
    return q & (Q(created_by=user) | Q(updated_by=user) | Q(locked_by=user))


def form_scope_q(user) -> Q:
    if not _is_authenticated(user):
        return Q(pk__isnull=True)
    if is_admin(user):
        return Q()
    profile = _access(user)
    if profile is None:
        return Q() if is_staff_user(user) else Q(pk__isnull=True)
    q = Q()
    form_keys = _list_from_profile(profile, "allowed_form_keys")
    if form_keys:
        q &= Q(key__in=form_keys)
    mode = _scope_mode(profile)
    if mode == "org_units":
        org_units = _list_from_profile(profile, "org_units")
        if not org_units:
            return Q(pk__isnull=True)
        q &= Q(org_unit__in=org_units)
    elif mode == "own":
        # "Own" users may create/view available forms; object data stays restricted by entry_scope_q.
        pass
    return q


def can_view_form(user, form) -> bool:
    if not can_view_forms(user):
        return False
    if is_admin(user):
        return True
    profile = _access(user)
    if profile is None:
        return bool(is_staff_user(user))
    if not _form_key_allowed(profile, getattr(form, "key", None)):
        return False
    mode = _scope_mode(profile)
    if mode == "all":
        return True
    if mode == "org_units":
        org_units = set(_list_from_profile(profile, "org_units"))
        org_unit = str(getattr(form, "org_unit", "") or "").strip()
        return bool(org_unit and org_unit in org_units)
    return True


def can_view_entry(user, entry) -> bool:
    """Object-level access gate for resident form entries."""
    if not can_view_forms(user):
        return False
    return _scope_allows_entry(user, entry)


def can_edit_entry(user, entry) -> bool:
    return bool(can_create_entries(user) and can_view_entry(user, entry))


def can_review_entry(user, entry) -> bool:
    return bool(can_review_entries(user) and can_view_entry(user, entry))


def can_send_entry(user, entry) -> bool:
    return bool(can_send_entries(user) and can_view_entry(user, entry))


def can_view_pdf_document(user, pdf_document) -> bool:
    if not pdf_document:
        return False
    return can_view_entry(user, getattr(pdf_document, "form_entry", None))


def can_view_outbox_item(user, outbox_item) -> bool:
    if not outbox_item:
        return False
    return can_view_entry(user, getattr(outbox_item, "form_entry", None))


def can_view_archive_record(user, archive_record) -> bool:
    if not archive_record or not can_view_archive(user):
        return False
    return can_view_entry(user, getattr(archive_record, "form_entry", None))
