from django.urls import path

from .attachment_views import attachment_delete_view, attachment_download_view
from .conditional_builder_views import (
    conditional_rule_create_view,
    conditional_rule_delete_view,
    conditional_rule_edit_view,
    conditional_rule_list_view,
)
from .docx_template_views import (
    docx_document_download_view,
    docx_template_detail_view,
    docx_template_file_view,
    docx_template_list_view,
    docx_template_upload_view,
    entry_docx_generate_view,
)
from .excel_import_views import (
    excel_import_detail_view,
    excel_import_generate_view,
    excel_import_list_view,
    excel_import_mapping_view,
    excel_import_upload_view,
)
from .pdf_template_views import (
    pdf_template_activate_view,
    pdf_template_detail_view,
    pdf_template_file_view,
    pdf_template_list_view,
    pdf_template_placement_create_view,
    pdf_template_placement_delete_view,
    pdf_template_placement_edit_view,
    pdf_template_upload_view,
)
from .repeatable_builder_views import (
    repeatable_column_create_view,
    repeatable_column_delete_view,
    repeatable_column_edit_view,
    repeatable_column_reorder_view,
    repeatable_group_create_view,
    repeatable_group_delete_view,
    repeatable_group_edit_view,
    repeatable_group_reorder_view,
)
from .repeatable_entry_views import (
    entry_create_view,
    entry_detail_view,
    entry_edit_view,
    entry_review_view,
    entry_save_view,
    entry_validate_view,
)
from .views import (
    archive_list_view,
    dashboard_view,
    draft_list_view,
    email_target_create_view,
    email_target_edit_view,
    email_target_list_view,
    entry_approve_view,
    entry_pdf_generate_view,
    entry_pdf_live_preview_view,
    entry_pdf_new_live_preview_view,
    entry_pdf_preview_view,
    entry_queue_view,
    entry_reject_view,
    entry_send_now_view,
    form_blank_pdf_view,
    form_builder_create_view,
    form_builder_edit_view,
    form_builder_list_view,
    form_field_create_view,
    form_field_delete_view,
    form_field_edit_view,
    form_field_reorder_view,
    form_list_view,
    form_section_create_view,
    form_section_delete_view,
    form_section_edit_view,
    form_section_reorder_view,
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
    staff_access_create_view,
    staff_access_edit_view,
    staff_access_list_view,
)

app_name = "form_builder"

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("formulare/", form_list_view, name="form_list"),
    path("formulare/<uuid:form_id>/neu/", entry_create_view, name="entry_create"),
    path("formulare/<uuid:form_id>/leer/pdf/", form_blank_pdf_view, name="form_blank_pdf"),
    path(
        "formulare/<uuid:form_id>/neu/pdf/live/",
        entry_pdf_new_live_preview_view,
        name="entry_pdf_new_live_preview",
    ),
    path("formulare/eintraege/<uuid:entry_id>/", entry_detail_view, name="entry_detail"),
    path("formulare/eintraege/<uuid:entry_id>/bearbeiten/", entry_edit_view, name="entry_edit"),
    path("formulare/eintraege/<uuid:entry_id>/speichern/", entry_save_view, name="entry_save"),
    path(
        "formulare/eintraege/<uuid:entry_id>/schicken/", entry_send_now_view, name="entry_send_now"
    ),
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
    path(
        "formulare/eintraege/<uuid:entry_id>/docx/erzeugen/",
        entry_docx_generate_view,
        name="entry_docx_generate",
    ),
    path("dokumente/pdf/<uuid:pdf_id>/", pdf_download_view, name="pdf_download"),
    path(
        "dokumente/docx/<uuid:document_id>/",
        docx_document_download_view,
        name="docx_document_download",
    ),
    path(
        "dokumente/anhang/<uuid:attachment_id>/",
        attachment_download_view,
        name="attachment_download",
    ),
    path(
        "dokumente/anhang/<uuid:attachment_id>/loeschen/",
        attachment_delete_view,
        name="attachment_delete",
    ),
    path("formulare/entwuerfe/", draft_list_view, name="draft_list"),
    path("formulare/review/", review_list_view, name="review_list"),
    path("formulare/ausgangskorb/", outbox_list_view, name="outbox_list"),
    path("formulare/ausgangskorb/verarbeiten/", process_outbox_view, name="outbox_process"),
    path("formulare/versandt/", sent_list_view, name="sent_list"),
    path("formulare/archiv/", archive_list_view, name="archive_list"),
    path("profil/", profile_view, name="profile"),
    path("einstellungen/", settings_index_view, name="settings_index"),
    path("einstellungen/docx-vorlagen/", docx_template_list_view, name="docx_template_list"),
    path(
        "einstellungen/docx-vorlagen/hochladen/",
        docx_template_upload_view,
        name="docx_template_upload",
    ),
    path(
        "einstellungen/docx-vorlagen/<uuid:template_id>/",
        docx_template_detail_view,
        name="docx_template_detail",
    ),
    path(
        "einstellungen/docx-vorlagen/<uuid:template_id>/datei/",
        docx_template_file_view,
        name="docx_template_file",
    ),
    path("einstellungen/excel-importe/", excel_import_list_view, name="excel_import_list"),
    path(
        "einstellungen/excel-importe/hochladen/",
        excel_import_upload_view,
        name="excel_import_upload",
    ),
    path(
        "einstellungen/excel-importe/<uuid:job_id>/",
        excel_import_detail_view,
        name="excel_import_detail",
    ),
    path(
        "einstellungen/excel-importe/<uuid:job_id>/mapping/",
        excel_import_mapping_view,
        name="excel_import_mapping",
    ),
    path(
        "einstellungen/excel-importe/<uuid:job_id>/generieren/",
        excel_import_generate_view,
        name="excel_import_generate",
    ),
    path("einstellungen/pdf-vorlagen/", pdf_template_list_view, name="pdf_template_list"),
    path(
        "einstellungen/pdf-vorlagen/hochladen/",
        pdf_template_upload_view,
        name="pdf_template_upload",
    ),
    path(
        "einstellungen/pdf-vorlagen/<uuid:template_id>/",
        pdf_template_detail_view,
        name="pdf_template_detail",
    ),
    path(
        "einstellungen/pdf-vorlagen/<uuid:template_id>/datei/",
        pdf_template_file_view,
        name="pdf_template_file",
    ),
    path(
        "einstellungen/pdf-vorlagen/<uuid:template_id>/aktivieren/",
        pdf_template_activate_view,
        name="pdf_template_activate",
    ),
    path(
        "einstellungen/pdf-vorlagen/<uuid:template_id>/platzierungen/neu/",
        pdf_template_placement_create_view,
        name="pdf_template_placement_create",
    ),
    path(
        "einstellungen/pdf-vorlagen/platzierungen/<uuid:placement_id>/bearbeiten/",
        pdf_template_placement_edit_view,
        name="pdf_template_placement_edit",
    ),
    path(
        "einstellungen/pdf-vorlagen/platzierungen/<uuid:placement_id>/loeschen/",
        pdf_template_placement_delete_view,
        name="pdf_template_placement_delete",
    ),
    path("einstellungen/form-builder/", form_builder_list_view, name="form_builder_list"),
    path("einstellungen/form-builder/neu/", form_builder_create_view, name="form_builder_create"),
    path(
        "einstellungen/form-builder/<uuid:form_id>/bearbeiten/",
        form_builder_edit_view,
        name="form_builder_edit",
    ),
    path(
        "einstellungen/form-builder/<uuid:form_id>/regeln/",
        conditional_rule_list_view,
        name="conditional_rule_list",
    ),
    path(
        "einstellungen/form-builder/<uuid:form_id>/regeln/neu/",
        conditional_rule_create_view,
        name="conditional_rule_create",
    ),
    path(
        "einstellungen/form-builder/regeln/<uuid:rule_id>/bearbeiten/",
        conditional_rule_edit_view,
        name="conditional_rule_edit",
    ),
    path(
        "einstellungen/form-builder/regeln/<uuid:rule_id>/loeschen/",
        conditional_rule_delete_view,
        name="conditional_rule_delete",
    ),
    path(
        "einstellungen/form-builder/<uuid:form_id>/abschnitte/neu/",
        form_section_create_view,
        name="form_section_create",
    ),
    path(
        "einstellungen/form-builder/abschnitte/<uuid:section_id>/bearbeiten/",
        form_section_edit_view,
        name="form_section_edit",
    ),
    path(
        "einstellungen/form-builder/abschnitte/<uuid:section_id>/loeschen/",
        form_section_delete_view,
        name="form_section_delete",
    ),
    path(
        "einstellungen/form-builder/abschnitte/<uuid:section_id>/<str:direction>/",
        form_section_reorder_view,
        name="form_section_reorder",
    ),
    path(
        "einstellungen/form-builder/<uuid:form_id>/felder/neu/",
        form_field_create_view,
        name="form_field_create",
    ),
    path(
        "einstellungen/form-builder/felder/<uuid:field_id>/bearbeiten/",
        form_field_edit_view,
        name="form_field_edit",
    ),
    path(
        "einstellungen/form-builder/felder/<uuid:field_id>/loeschen/",
        form_field_delete_view,
        name="form_field_delete",
    ),
    path(
        "einstellungen/form-builder/felder/<uuid:field_id>/<str:direction>/",
        form_field_reorder_view,
        name="form_field_reorder",
    ),
    path(
        "einstellungen/form-builder/<uuid:form_id>/tabellen/neu/",
        repeatable_group_create_view,
        name="repeatable_group_create",
    ),
    path(
        "einstellungen/form-builder/tabellen/<uuid:group_id>/bearbeiten/",
        repeatable_group_edit_view,
        name="repeatable_group_edit",
    ),
    path(
        "einstellungen/form-builder/tabellen/<uuid:group_id>/loeschen/",
        repeatable_group_delete_view,
        name="repeatable_group_delete",
    ),
    path(
        "einstellungen/form-builder/tabellen/<uuid:group_id>/<str:direction>/",
        repeatable_group_reorder_view,
        name="repeatable_group_reorder",
    ),
    path(
        "einstellungen/form-builder/tabellen/<uuid:group_id>/spalten/neu/",
        repeatable_column_create_view,
        name="repeatable_column_create",
    ),
    path(
        "einstellungen/form-builder/tabellen/spalten/<uuid:column_id>/bearbeiten/",
        repeatable_column_edit_view,
        name="repeatable_column_edit",
    ),
    path(
        "einstellungen/form-builder/tabellen/spalten/<uuid:column_id>/loeschen/",
        repeatable_column_delete_view,
        name="repeatable_column_delete",
    ),
    path(
        "einstellungen/form-builder/tabellen/spalten/<uuid:column_id>/<str:direction>/",
        repeatable_column_reorder_view,
        name="repeatable_column_reorder",
    ),
    path("einstellungen/email/", email_target_list_view, name="email_target_list"),
    path("einstellungen/email/neu/", email_target_create_view, name="email_target_create"),
    path(
        "einstellungen/email/<uuid:recipient_id>/bearbeiten/",
        email_target_edit_view,
        name="email_target_edit",
    ),
    path("einstellungen/mitarbeiter/", staff_access_list_view, name="staff_access_list"),
    path("einstellungen/mitarbeiter/neu/", staff_access_create_view, name="staff_access_create"),
    path(
        "einstellungen/mitarbeiter/<uuid:profile_id>/bearbeiten/",
        staff_access_edit_view,
        name="staff_access_edit",
    ),
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
