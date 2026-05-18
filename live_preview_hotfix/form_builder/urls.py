from django.urls import path

from .views import (
    archive_list_view,
    dashboard_view,
    draft_list_view,
    entry_approve_view,
    entry_create_view,
    entry_detail_view,
    entry_edit_view,
    entry_pdf_generate_view,
    entry_pdf_live_preview_view,
    entry_pdf_new_live_preview_view,
    entry_pdf_preview_view,
    entry_queue_view,
    entry_reject_view,
    entry_review_view,
    entry_save_view,
    entry_validate_view,
    form_list_view,
    outbox_list_view,
    pdf_download_view,
    process_outbox_view,
    process_schedules_view,
    profile_view,
    review_list_view,
    schedule_create_view,
    schedule_edit_view,
    schedule_list_view,
    schedule_toggle_view,
    sent_list_view,
    settings_index_view,
)

app_name = "form_builder"


urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("formulare/", form_list_view, name="form_list"),
    path("formulare/<uuid:form_id>/neu/", entry_create_view, name="entry_create"),
    path(
        "formulare/<uuid:form_id>/neu/pdf/live/",
        entry_pdf_new_live_preview_view,
        name="entry_pdf_new_live_preview",
    ),
    path("formulare/eintraege/<uuid:entry_id>/", entry_detail_view, name="entry_detail"),
    path("formulare/eintraege/<uuid:entry_id>/bearbeiten/", entry_edit_view, name="entry_edit"),
    path("formulare/eintraege/<uuid:entry_id>/speichern/", entry_save_view, name="entry_save"),
    path(
        "formulare/eintraege/<uuid:entry_id>/validieren/",
        entry_validate_view,
        name="entry_validate",
    ),
    path("formulare/eintraege/<uuid:entry_id>/review/", entry_review_view, name="entry_review"),
    path(
        "formulare/eintraege/<uuid:entry_id>/freigeben/", entry_approve_view, name="entry_approve"
    ),
    path(
        "formulare/eintraege/<uuid:entry_id>/zurueckweisen/", entry_reject_view, name="entry_reject"
    ),
    path("formulare/eintraege/<uuid:entry_id>/ausgangskorb/", entry_queue_view, name="entry_queue"),
    path(
        "formulare/eintraege/<uuid:entry_id>/pdf/", entry_pdf_preview_view, name="entry_pdf_preview"
    ),
    path(
        "formulare/eintraege/<uuid:entry_id>/pdf/live/",
        entry_pdf_live_preview_view,
        name="entry_pdf_live_preview",
    ),
    path(
        "formulare/eintraege/<uuid:entry_id>/pdf/erzeugen/",
        entry_pdf_generate_view,
        name="entry_pdf_generate",
    ),
    path("dokumente/pdf/<uuid:pdf_id>/", pdf_download_view, name="pdf_download"),
    path("formulare/entwuerfe/", draft_list_view, name="draft_list"),
    path("formulare/review/", review_list_view, name="review_list"),
    path("formulare/ausgangskorb/", outbox_list_view, name="outbox_list"),
    path("formulare/ausgangskorb/verarbeiten/", process_outbox_view, name="outbox_process"),
    path("formulare/versandt/", sent_list_view, name="sent_list"),
    path("formulare/archiv/", archive_list_view, name="archive_list"),
    path("profil/", profile_view, name="profile"),
    path("einstellungen/", settings_index_view, name="settings_index"),
    path("einstellungen/zeitplaene/", schedule_list_view, name="schedule_list"),
    path("einstellungen/zeitplaene/neu/", schedule_create_view, name="schedule_create"),
    path(
        "einstellungen/zeitplaene/<uuid:schedule_id>/bearbeiten/",
        schedule_edit_view,
        name="schedule_edit",
    ),
    path(
        "einstellungen/zeitplaene/<uuid:schedule_id>/umschalten/",
        schedule_toggle_view,
        name="schedule_toggle",
    ),
    path("einstellungen/zeitplaene/verarbeiten/", process_schedules_view, name="schedule_process"),
]
