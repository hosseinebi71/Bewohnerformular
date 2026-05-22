from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from form_builder.models import Field, Form, FormSection, UserAccessProfile


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class FormBuilderUITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="builder_admin",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )
        self.staff = User.objects.create_user(username="builder_staff", password="pass")
        UserAccessProfile.objects.create(
            user=self.staff,
            can_dashboard=True,
            can_forms=True,
            can_settings=True,
            can_manage_settings=False,
        )

    def test_builder_list_requires_manage_settings_permission(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("form_builder:form_builder_list"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_form_metadata(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("form_builder:form_builder_create"),
            {
                "key": "hygiene-kontrolle",
                "version": 1,
                "title": "Hygiene Kontrolle",
                "description": "Digitale Hygienepruefung",
                "org_unit": "haus-a",
                "status": Form.PublicationStatus.DRAFT,
                "review_required": "on",
                "is_archivable": "on",
                "retention_period_days": 3650,
            },
        )

        form_definition = Form.objects.get(key="hygiene-kontrolle")
        self.assertRedirects(
            response,
            reverse("form_builder:form_builder_edit", args=[form_definition.pk]),
        )
        self.assertEqual(form_definition.title, "Hygiene Kontrolle")
        self.assertEqual(form_definition.created_by, self.admin)
        self.assertEqual(form_definition.schema["fields"], [])

    def test_admin_can_create_section_and_select_field(self):
        form_definition = Form.objects.create(
            key="builder-form",
            version=1,
            title="Builder Form",
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.client.force_login(self.admin)

        section_response = self.client.post(
            reverse("form_builder:form_section_create", args=[form_definition.pk]),
            {
                "position": 1,
                "title": "Hygiene",
                "description": "Kontrollpunkte",
                "is_collapsible": "on",
                "is_active": "on",
            },
        )
        self.assertRedirects(
            section_response,
            reverse("form_builder:form_builder_edit", args=[form_definition.pk]),
        )
        section = FormSection.objects.get(form=form_definition, title="Hygiene")

        field_response = self.client.post(
            reverse("form_builder:form_field_create", args=[form_definition.pk]),
            {
                "section": str(section.pk),
                "position": 1,
                "key": "kontrolle_ok",
                "label": "Kontrolle OK?",
                "field_type": Field.FieldType.SELECT,
                "required": "on",
                "help_text": "Status der Kontrolle",
                "placeholder": "",
                "choices_text": "ok|OK\nnicht_ok|Nicht OK",
                "is_active": "on",
            },
        )
        self.assertRedirects(
            field_response,
            reverse("form_builder:form_builder_edit", args=[form_definition.pk]),
        )

        field = Field.objects.get(form=form_definition, key="kontrolle_ok")
        self.assertEqual(field.section, section)
        self.assertEqual(field.choices[1], {"value": "nicht_ok", "label": "Nicht OK"})
        self.assertTrue(field.required)
        form_definition.refresh_from_db()
        self.assertEqual(form_definition.schema["sections"][0]["title"], "Hygiene")
        self.assertEqual(form_definition.schema["fields"][0]["key"], "kontrolle_ok")

    def test_admin_can_create_signature_field(self):
        form_definition = Form.objects.create(key="signature-form", version=1, title="Signature")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("form_builder:form_field_create", args=[form_definition.pk]),
            {
                "position": 1,
                "key": "unterschrift",
                "label": "Unterschrift",
                "field_type": "signature",
                "required": "on",
                "help_text": "",
                "placeholder": "",
                "choices_text": "",
                "is_active": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("form_builder:form_builder_edit", args=[form_definition.pk]),
        )
        field = Field.objects.get(form=form_definition, key="unterschrift")
        self.assertEqual(field.field_type, Field.FieldType.TEXT)
        self.assertEqual(field.ui_config["widget"], "signature")

    def test_reorder_sections_swaps_positions(self):
        form_definition = Form.objects.create(key="order-form", version=1, title="Order")
        first = FormSection.objects.create(form=form_definition, title="A", position=1)
        second = FormSection.objects.create(form=form_definition, title="B", position=2)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("form_builder:form_section_reorder", args=[second.pk, "up"])
        )

        self.assertRedirects(
            response,
            reverse("form_builder:form_builder_edit", args=[form_definition.pk]),
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.position, 2)
        self.assertEqual(second.position, 1)

    def test_published_form_structure_is_locked(self):
        form_definition = Form.objects.create(
            key="published-builder",
            version=1,
            title="Published Builder",
            status=Form.PublicationStatus.PUBLISHED,
            published_at=timezone.now(),
            schema={"fields": []},
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("form_builder:form_section_create", args=[form_definition.pk]),
            {"position": 1, "title": "Locked", "is_active": "on"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(FormSection.objects.filter(form=form_definition).exists())
