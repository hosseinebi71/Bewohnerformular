from django.contrib.auth import get_user_model
from django.test import TestCase

from form_builder.conditional_models import ConditionalRule
from form_builder.conditional_services import apply_conditional_rules_to_form
from form_builder.models import Bewohner, Field, Form, FormEntry
from form_builder.services import build_entry_form, create_form_entry_from_validated


class ConditionalRuleTests(TestCase):
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
        self.trigger = Field.objects.create(
            form=self.form,
            key="mangel_vorhanden",
            label="Mangel vorhanden",
            field_type=Field.FieldType.SELECT,
            position=1,
            choices=[{"value": "yes", "label": "Ja"}, {"value": "no", "label": "Nein"}],
            created_by=self.user,
            updated_by=self.user,
        )
        self.description = Field.objects.create(
            form=self.form,
            key="mangel_beschreibung",
            label="Beschreibung",
            field_type=Field.FieldType.TEXTAREA,
            position=2,
            required=False,
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

    def test_conditional_required_validation_blocks_missing_target(self):
        ConditionalRule.objects.create(
            form=self.form,
            source_field=self.trigger,
            operator=ConditionalRule.Operator.EQUALS,
            value="yes",
            action=ConditionalRule.Action.REQUIRE,
            target_field=self.description,
            message="Bitte den Mangel beschreiben.",
            created_by=self.user,
            updated_by=self.user,
        )
        entry_form = build_entry_form(
            self.form,
            data={"mangel_vorhanden": "yes", "mangel_beschreibung": ""},
        )
        self.assertTrue(entry_form.is_valid())
        is_valid = apply_conditional_rules_to_form(
            form=entry_form,
            form_definition=self.form,
            schema=self.form.schema,
            cleaned_data=entry_form.cleaned_data,
        )
        self.assertFalse(is_valid)
        self.assertIn("mangel_beschreibung", entry_form.errors)

    def test_conditional_required_validation_allows_non_matching_source(self):
        ConditionalRule.objects.create(
            form=self.form,
            source_field=self.trigger,
            operator=ConditionalRule.Operator.EQUALS,
            value="yes",
            action=ConditionalRule.Action.REQUIRE,
            target_field=self.description,
            created_by=self.user,
            updated_by=self.user,
        )
        entry_form = build_entry_form(
            self.form,
            data={"mangel_vorhanden": "no", "mangel_beschreibung": ""},
        )
        self.assertTrue(entry_form.is_valid())
        is_valid = apply_conditional_rules_to_form(
            form=entry_form,
            form_definition=self.form,
            schema=self.form.schema,
            cleaned_data=entry_form.cleaned_data,
        )
        self.assertTrue(is_valid)

    def test_valid_conditional_submission_can_be_saved(self):
        ConditionalRule.objects.create(
            form=self.form,
            source_field=self.trigger,
            operator=ConditionalRule.Operator.EQUALS,
            value="yes",
            action=ConditionalRule.Action.REQUIRE,
            target_field=self.description,
            created_by=self.user,
            updated_by=self.user,
        )
        entry_form = build_entry_form(
            self.form,
            data={"mangel_vorhanden": "yes", "mangel_beschreibung": "Defekter Spender"},
        )
        self.assertTrue(entry_form.is_valid())
        self.assertTrue(
            apply_conditional_rules_to_form(
                form=entry_form,
                form_definition=self.form,
                schema=self.form.schema,
                cleaned_data=entry_form.cleaned_data,
            )
        )
        entry = create_form_entry_from_validated(
            form_definition=self.form,
            bewohner=self.bewohner,
            cleaned_data=entry_form.cleaned_data,
            user=self.user,
        )
        self.assertEqual(entry.data["mangel_beschreibung"], "Defekter Spender")

    def test_rule_references_must_belong_to_same_form(self):
        other_form = Form.objects.create(key="other", version=1, title="Other")
        other_field = Field.objects.create(
            form=other_form,
            key="other_field",
            label="Other",
            field_type=Field.FieldType.TEXT,
            position=1,
        )
        rule = ConditionalRule(
            form=self.form,
            source_field=other_field,
            operator=ConditionalRule.Operator.IS_NOT_EMPTY,
            action=ConditionalRule.Action.SHOW,
            target_field=self.description,
        )
        with self.assertRaises(Exception):
            rule.full_clean()
