from django.contrib.auth import get_user_model
from django.test import TestCase

from form_builder.models import Bewohner, Field, Form, FormEntry
from form_builder.repeatable_models import RepeatableGroup, RepeatableGroupColumn
from form_builder.repeatable_services import (
    apply_repeatable_payload,
    get_augmented_form_schema,
    parse_repeatable_groups_from_post,
)


class RepeatableGroupTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="x", is_staff=True)
        self.form = Form.objects.create(key="hygiene", version=1, title="Hygiene Kontrolle")
        Field.objects.create(form=self.form, key="name", label="Name", field_type=Field.FieldType.TEXT, position=1)
        self.group = RepeatableGroup.objects.create(
            form=self.form, key="kontrollen", title="Kontrollpunkte", position=1, min_rows=1, max_rows=5
        )
        RepeatableGroupColumn.objects.create(
            group=self.group, key="bereich", label="Bereich", column_type="text", position=1, required=True
        )
        RepeatableGroupColumn.objects.create(
            group=self.group, key="ok", label="OK", column_type="boolean", position=2
        )
        self.form.sync_schema()
        self.form.publish()
        self.form.refresh_from_db()
        self.bewohner = Bewohner.objects.create(resident_number="B-1", first_name="A", last_name="B")

    def test_schema_contains_repeatable_group(self):
        schema = get_augmented_form_schema(self.form)
        self.assertEqual(schema["repeatable_groups"][0]["key"], "kontrollen")
        self.assertEqual(schema["repeatable_groups"][0]["columns"][0]["key"], "bereich")

    def test_parse_repeatable_group_rows(self):
        schema = get_augmented_form_schema(self.form)
        post = {
            "__repeatable_kontrollen_row_count": "1",
            "repeatable__kontrollen__0__bereich": "Kueche",
            "repeatable__kontrollen__0__ok": "1",
        }
        payload = parse_repeatable_groups_from_post(schema, post)
        self.assertEqual(payload["kontrollen"][0]["bereich"], "Kueche")
        self.assertTrue(payload["kontrollen"][0]["ok"])

    def test_required_column_is_validated(self):
        schema = get_augmented_form_schema(self.form)
        post = {"__repeatable_kontrollen_row_count": "1", "repeatable__kontrollen__0__ok": "1"}
        with self.assertRaises(Exception):
            parse_repeatable_groups_from_post(schema, post)

    def test_apply_repeatable_payload_to_entry_data(self):
        schema = get_augmented_form_schema(self.form)
        entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            form_snapshot=schema,
            data={"name": "Test"},
            created_by=self.user,
            updated_by=self.user,
        )
        post = {
            "__repeatable_kontrollen_row_count": "1",
            "repeatable__kontrollen__0__bereich": "Bad",
            "repeatable__kontrollen__0__ok": "1",
        }
        apply_repeatable_payload(form_entry=entry, post_data=post, user=self.user)
        entry.refresh_from_db()
        self.assertEqual(entry.data["kontrollen"][0]["bereich"], "Bad")
