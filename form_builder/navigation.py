from .permissions import can_view_archive, can_view_dashboard, can_view_forms, can_view_settings


def get_navigation_items(user, *, current_url_name: str | None = None) -> list[dict]:
    settings_active = current_url_name in {
        "form_builder:settings_index",
        "form_builder:schedule_list",
        "form_builder:profile",
    }
    items = [
        {
            "label": "Dashboard",
            "url_name": "form_builder:dashboard",
            "visible": can_view_dashboard(user),
            "section": "dashboard",
            "icon": "D",
        },
        {
            "label": "Formulare",
            "url_name": "form_builder:form_list",
            "visible": can_view_forms(user),
            "section": "forms",
            "icon": "F",
        },
        {
            "label": "Entwuerfe",
            "url_name": "form_builder:draft_list",
            "visible": can_view_forms(user),
            "section": "drafts",
            "icon": "E",
        },
        {
            "label": "Versandt",
            "url_name": "form_builder:sent_list",
            "visible": can_view_forms(user),
            "section": "sent",
            "icon": "S",
        },
        {
            "label": "Archiv",
            "url_name": "form_builder:archive_list",
            "visible": can_view_archive(user),
            "section": "archive",
            "icon": "A",
        },
        {
            "label": "Einstellungen",
            "url_name": "form_builder:settings_index",
            "visible": can_view_settings(user),
            "section": "settings",
            "icon": "K",
            "force_active": settings_active,
        },
    ]

    visible_items = [item for item in items if item["visible"]]
    for item in visible_items:
        item["active"] = bool(item.get("force_active") or item["url_name"] == current_url_name)
    return visible_items
