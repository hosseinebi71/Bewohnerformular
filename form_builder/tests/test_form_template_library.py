from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from form_builder.form_template_models import FormTemplate
from form_builder.form_template_services import copy_template_to_form
from form_builder.models import Field, Form


class FormTemplateLibraryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("admin", password="test", is_staff=True, is_superuser=True)

    def test_seed_starter_templates_is_idempotent(self):
        call_command("seed_starter_templates", verbosity=0)
        first_count = FormTemplate.objects.count()
        self.assertGreaterEqual(first_count, 8)
        call_command("seed_starter_templates", verbosity=0)
        self.assertEqual(FormTemplate.objects.count(), first_count)

    def test_copy_template_creates_editable_draft_form(self):
        template = FormTemplate.objects.create(
            key="simple-template",
            version=1,
            title="Simple Template",
            category="Test",
            definition={
                "form": {"key": "copied-form", "title": "Copied Form"},
                "fields": [
                    {"key": "datum", "label": "Datum", "field_type": "date", "required": True},
                    {"key": "bemerkung", "label": "Bemerkung", "field_type": "textarea"},
                ],
            },
        )
        result = copy_template_to_form(template=template, user=self.user)
        self.assertEqual(result.form.status, Form.PublicationStatus.DRAFT)
        self.assertEqual(result.fields_created, 2)
        self.assertTrue(Field.objects.filter(form=result.form, key="datum", required=True).exists())
        self.assertEqual(result.form.schema["template_source"]["template_key"], "simple-template")

    def test_template_list_requires_settings_access(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("form_builder:form_template_list"))
        self.assertEqual(response.status_code, 200)
