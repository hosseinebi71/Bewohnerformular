from django.apps import AppConfig


class FormBuilderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "form_builder"
    verbose_name = "Bewohner-Formularsystem"

    def ready(self):
        # Keep extension models loaded for admin, permission checks and migrations while
        # avoiding a large refactor of the existing monolithic models.py file.
        import form_builder.action_item_models  # noqa: F401
        import form_builder.attachment_models  # noqa: F401
        import form_builder.conditional_models  # noqa: F401
        import form_builder.docx_template_models  # noqa: F401
        import form_builder.excel_import_models  # noqa: F401
        import form_builder.form_template_models  # noqa: F401
        import form_builder.pdf_template_models  # noqa: F401
        import form_builder.qr_context_models  # noqa: F401
        import form_builder.repeatable_models  # noqa: F401
        from form_builder.pdf_template_services import register_pdf_template_renderer

        register_pdf_template_renderer()
