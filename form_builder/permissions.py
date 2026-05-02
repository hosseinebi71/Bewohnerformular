ADMIN_GROUP = "Admin"
STAFF_GROUP = "Staff"
VIEWER_GROUP = "Viewer"


def _is_authenticated(user) -> bool:
    return bool(user and user.is_authenticated)


def _has_group(user, group_name: str) -> bool:
    if not _is_authenticated(user):
        return False
    return user.groups.filter(name=group_name).exists()


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
    return bool(_is_authenticated(user) and (is_admin(user) or is_staff_user(user) or _has_group(user, VIEWER_GROUP)))


def can_view_forms(user) -> bool:
    return can_view_dashboard(user)


def can_create_entries(user) -> bool:
    return bool(_is_authenticated(user) and (is_admin(user) or is_staff_user(user)))


def can_review_entries(user) -> bool:
    """Users allowed to approve or reject submitted entries."""
    return bool(_is_authenticated(user) and (is_admin(user) or is_staff_user(user)))


def can_send_entries(user) -> bool:
    """Users allowed to move approved entries into the secure outbox."""
    return bool(_is_authenticated(user) and (is_admin(user) or is_staff_user(user)))


def can_view_settings(user) -> bool:
    return bool(_is_authenticated(user) and (is_admin(user) or is_staff_user(user)))


def can_manage_settings(user) -> bool:
    return is_admin(user)
