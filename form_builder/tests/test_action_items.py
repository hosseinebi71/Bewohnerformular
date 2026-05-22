from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from form_builder.action_item_models import ActionItem, ActionItemReminderLog, ActionItemRule
from form_builder.action_item_services import process_reminders, sync_action_items_for_entry
from form_builder.models import Bewohner, Field, Form, FormEntry


class ActionItemTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="admin", password="test", is_staff=True)
        self.form = Form.objects.create(
            key="hygiene-kontrolle",
            version=1,
            title="Hygiene Kontrolle",
            status=Form.PublicationStatus.DRAFT,
            created_by=self.user,
            updated_by=self.user,
        )
        self.mangel = Field.objects.create(
            form=self.form,
            key="mangel_vorhanden",
            label="Mangel vorhanden",
            field_type=Field.FieldType.SELECT,
            position=1,
            choices=[{"value": "yes", "label": "Ja"}, {"value": "no", "label": "Nein"}],
            created_by=self.user,
            updated_by=self.user,
        )
        Field.objects.create(
            form=self.form,
            key="massnahme",
            label="Massnahme",
            field_type=Field.FieldType.TEXTAREA,
            position=2,
            created_by=self.user,
            updated_by=self.user,
        )
        self.form.sync_schema()
        self.bewohner = Bewohner.objects.create(
            resident_number="R-1",
            first_name="Max",
            last_name="Muster",
            created_by=self.user,
            updated_by=self.user,
        )

    def _entry(self, data):
        return FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            status=FormEntry.EntryStatus.IN_REVIEW,
            form_snapshot=self.form.schema,
            data=data,
            submitted_at=timezone.now(),
            created_by=self.user,
            updated_by=self.user,
        )

    def test_simple_rule_creates_action_item_and_is_idempotent(self):
        ActionItemRule.objects.create(
            form=self.form,
            name="Mangel erzeugt Massnahme",
            source_field=self.mangel,
            operator=ActionItemRule.Operator.EQUALS,
            value="yes",
            title_template="Mangel: {field_value}",
            description_template="{massnahme}",
            priority=ActionItem.Priority.HIGH,
            created_by=self.user,
            updated_by=self.user,
        )
        entry = self._entry({"mangel_vorhanden": "yes", "massnahme": "Spender ersetzen"})

        first = sync_action_items_for_entry(form_entry=entry, user=self.user)
        second = sync_action_items_for_entry(form_entry=entry, user=self.user)

        self.assertEqual(first.created, 1)
        self.assertEqual(second.created, 0)
        item = ActionItem.objects.get(source_entry=entry)
        self.assertEqual(item.priority, ActionItem.Priority.HIGH)
        self.assertIn("Spender ersetzen", item.description)

    def test_ok_value_creates_no_action_item(self):
        ActionItemRule.objects.create(
            form=self.form,
            name="Mangel erzeugt Massnahme",
            source_field=self.mangel,
            operator=ActionItemRule.Operator.EQUALS,
            value="yes",
        )
        entry = self._entry({"mangel_vorhanden": "no"})

        result = sync_action_items_for_entry(form_entry=entry, user=self.user)

        self.assertEqual(result.created, 0)
        self.assertFalse(ActionItem.objects.exists())

    def test_repeatable_nicht_ok_row_creates_one_task(self):
        ActionItemRule.objects.create(
            form=self.form,
            name="Nicht OK",
            source_group_key="kontrollen",
            source_column_key="nicht_ok",
            operator=ActionItemRule.Operator.BOOLEAN_TRUE,
            title_template="{bereich} - {kontrollpunkt}",
            description_template="{massnahme}",
            assigned_to_field_key="verantwortlich",
            due_at_field_key="frist",
            priority=ActionItem.Priority.HIGH,
        )
        entry = self._entry(
            {
                "kontrollen": [
                    {
                        "bereich": "Kueche",
                        "kontrollpunkt": "Seife",
                        "nicht_ok": True,
                        "massnahme": "Auffuellen",
                        "verantwortlich": "Team A",
                        "frist": "2030-01-15",
                    },
                    {"bereich": "Bad", "kontrollpunkt": "Boden", "nicht_ok": False},
                ]
            }
        )

        result = sync_action_items_for_entry(form_entry=entry, user=self.user)

        self.assertEqual(result.created, 1)
        item = ActionItem.objects.get()
        self.assertEqual(item.source_group_key, "kontrollen")
        self.assertEqual(item.source_row_key, "0")
        self.assertEqual(item.assigned_to_label, "Team A")
        self.assertEqual(item.due_at.date().isoformat(), "2030-01-15")

    def test_reminders_are_deduplicated(self):
        entry = self._entry({"mangel_vorhanden": "yes"})
        ActionItem.objects.create(
            source_entry=entry,
            source_field_key="mangel_vorhanden",
            source_rule_key="manual-test",
            title="Ueberfaellige Massnahme",
            due_at=timezone.now() - timedelta(days=4),
            created_by=self.user,
            updated_by=self.user,
        )

        first = process_reminders(due_soon_days=2, escalate_after_days=3)
        second = process_reminders(due_soon_days=2, escalate_after_days=3)

        self.assertGreaterEqual(first.action_overdue, 1)
        self.assertEqual(second.action_overdue, 0)
        self.assertTrue(ActionItemReminderLog.objects.filter(kind="overdue").exists())
