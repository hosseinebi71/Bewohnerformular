from django.apps import AppConfig


class FormBuilderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "form_builder"
    verbose_name = "Bewohner-Formularsystem"

    def ready(self):
        # Keep extension models loaded without forcing a risky rewrite of the
        # existing monolithic models.py file. The modules register Django models
        # and install small runtime integrations for schema/PDF handling.
        import form_builder.attachment_models  # noqa: F401
        import form_builder.repeatable_models  # noqa: F401
        from form_builder.repeatable_services import install_repeatable_runtime_patches

        install_repeatable_runtime_patches()
