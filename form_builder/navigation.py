from .permissions import can_view_dashboard, can_view_forms, can_view_settings


def get_navigation_items(user, *, current_url_name: str | None = None) -> list[dict]:
    items = [
        {
            "label": "Dashboard",
            "url_name": "form_builder:dashboard",
            "visible": can_view_dashboard(user),
            "section": "dashboard",
        },
        {
            "label": "Formulare",
            "url_name": "form_builder:form_list",
            "visible": can_view_forms(user),
            "section": "forms",
        },
        {
            "label": "Entwuerfe",
            "url_name": "form_builder:draft_list",
            "visible": can_view_forms(user),
            "section": "drafts",
        },
        {
            "label": "Review",
            "url_name": "form_builder:review_list",
            "visible": can_view_forms(user),
            "section": "review",
        },
        {
            "label": "Ausgangskorb",
            "url_name": "form_builder:outbox_list",
            "visible": can_view_forms(user),
            "section": "outbox",
        },
        {
            "label": "Versandt",
            "url_name": "form_builder:sent_list",
            "visible": can_view_forms(user),
            "section": "sent",
        },
        {
            "label": "Archiv",
            "url_name": "form_builder:archive_list",
            "visible": can_view_forms(user),
            "section": "archive",
        },
        {
            "label": "Profil",
            "url_name": "form_builder:profile",
            "visible": bool(user and user.is_authenticated),
            "section": "profile",
        },
        {
            "label": "Zeitplaene",
            "url_name": "form_builder:schedule_list",
            "visible": can_view_settings(user),
            "section": "schedules",
        },
        {
            "label": "Einstellungen",
            "url_name": "form_builder:settings_index",
            "visible": can_view_settings(user),
            "section": "settings",
        },
    ]

    visible_items = [item for item in items if item["visible"]]
    for item in visible_items:
        item["active"] = item["url_name"] == current_url_name
    return visible_items
