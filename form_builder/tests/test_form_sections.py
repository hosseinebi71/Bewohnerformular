from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from form_builder.models import Bewohner, Field, Form, FormEntry, FormSection
from form_builder.services import build_entry_form, get_form_schema


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class FormSectionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="section_user", password="pass", is_staff=True)
        self.form = Form.objects.create(key="section-test", version=1, title="Section Test")
        self.bewohner = Bewohner.objects.create(
            resident_number="SECT-001",
            first_name="Section",
            last_name="Test",
        )

    def _field(self, *, key, label, position, section=None, field_type=Field.FieldType.TEXT):
        return Field.objects.create(
            form=self.form,
            section=section,
            key=key,
            label=label,
            field_type=field_type,
            position=position,
        )

    def test_form_without_sections_keeps_flat_fields_schema(self):
        self._field(key="name", label="Name", position=1)

        schema = self.form.build_schema()

        self.assertEqual(schema["sections"], [])
        self.assertEqual([field["key"] for field in schema["fields"]], ["name"])
        self.assertIsNone(schema["fields"][0]["section_id"])

    def test_form_with_sections_adds_section_structure_and_keeps_full_flat_fields(self):
        second = FormSection.objects.create(form=self.form, title="Zweiter Abschnitt", position=2)
        first = FormSection.objects.create(
            form=self.form,
            title="Erster Abschnitt",
            description="Wichtige Daten",
            position=1,
            is_collapsible=True,
        )
        self._field(key="global", label="Global", position=3)
        self._field(key="first_name", label="Vorname", position=1, section=first)
        self._field(key="second_name", label="Nachname", position=2, section=second)

        schema = self.form.build_schema()

        self.assertEqual(
            [section["title"] for section in schema["sections"]],
            ["Erster Abschnitt", "Zweiter Abschnitt"],
        )
        self.assertEqual(schema["sections"][0]["description"], "Wichtige Daten")
        self.assertTrue(schema["sections"][0]["is_collapsible"])
        self.assertEqual(schema["sections"][0]["field_keys"], ["first_name"])
        self.assertEqual(
            [field["key"] for field in schema["fields"]],
            ["first_name", "second_name", "global"],
        )

    def test_dynamic_entry_form_exposes_sectioned_bound_field_groups(self):
        section = FormSection.objects.create(form=self.form, title="Kontaktdaten", position=1)
        self._field(key="email", label="E-Mail", position=1, section=section, field_type=Field.FieldType.EMAIL)
        self._field(key="note", label="Notiz", position=2, field_type=Field.FieldType.TEXTAREA)
        self.form.sync_schema()

        entry_form = build_entry_form(self.form)
        groups = entry_form.sectioned_bound_field_groups

        self.assertIn("email", entry_form.fields)
        self.assertIn("note", entry_form.fields)
        self.assertEqual(groups[0]["section"]["title"], "Kontaktdaten")
        self.assertEqual([field.name for field in groups[0]["fields"]], ["email"])
        self.assertIsNone(groups[1]["section"])
        self.assertEqual([field.name for field in groups[1]["fields"]], ["note"])

    def test_entry_snapshot_preserves_section_structure(self):
        section = FormSection.objects.create(form=self.form, title="Info", position=1)
        self._field(key="notes", label="Notizen", position=1, section=section, field_type=Field.FieldType.TEXTAREA)
        self.form.sync_schema()

        entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            form_snapshot=get_form_schema(self.form),
            data={"notes": "ok"},
            created_by=self.user,
            updated_by=self.user,
        )

        self.assertEqual(entry.form_snapshot["sections"][0]["title"], "Info")
        self.assertEqual(entry.form_snapshot["fields"][0]["key"], "notes")

    def test_inactive_sections_and_their_fields_are_excluded_from_schema(self):
        inactive = FormSection.objects.create(
            form=self.form,
            title="Inaktiv",
            position=1,
            is_active=False,
        )
        self._field(key="hidden", label="Hidden", position=1, section=inactive)

        schema = self.form.build_schema()

        self.assertEqual(schema["sections"], [])
        self.assertEqual(schema["fields"], [])

    def test_field_rejects_section_from_another_form(self):
        other_form = Form.objects.create(key="other-section-test", version=1, title="Other")
        foreign_section = FormSection.objects.create(
            form=other_form,
            title="Foreign",
            position=1,
        )
        field = Field(
            form=self.form,
            section=foreign_section,
            key="bad",
            label="Bad",
            field_type=Field.FieldType.TEXT,
            position=1,
        )

        with self.assertRaises(ValidationError):
            field.full_clean()

    def test_entry_create_template_renders_section_headers_and_fields(self):
        section = FormSection.objects.create(
            form=self.form,
            title="Bewohner-Daten",
            description="Basisdaten zur Erfassung",
            position=1,
        )
        self._field(key="vorname", label="Vorname", position=1, section=section)
        self._field(key="nachname", label="Nachname", position=2)
        self.form.status = Form.PublicationStatus.PUBLISHED
        self.form.published_at = timezone.now()
        self.form.sync_schema(save=False)
        self.form.save(update_fields=["status", "published_at", "schema", "updated_at"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("form_builder:entry_create", args=[self.form.pk]))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("Bewohner-Daten", html)
        self.assertIn("Basisdaten zur Erfassung", html)
        self.assertIn("Vorname", html)
        self.assertIn("Nachname", html)
