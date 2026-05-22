from django.apps import AppConfig


class FormBuilderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "form_builder"
    verbose_name = "Bewohner-Formularsystem"

    def ready(self):
        # Keep attachment models loaded for admin, permission checks and migrations while
        # avoiding a large refactor of the existing monolithic models.py file.
        import form_builder.attachment_models  # noqa: F401
