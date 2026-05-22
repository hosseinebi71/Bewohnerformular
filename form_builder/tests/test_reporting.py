from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook

from form_builder.action_item_models import ActionItem
from form_builder.models import Bewohner, Field, Form, FormEntry, OutboxItem
from form_builder.reporting_services import (
    export_entries_to_xlsx,
    get_operational_dashboard_data,
    render_monthly_report_pdf,
)


class ReportingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("manager", password="test", is_staff=True)
        self.form = Form.objects.create(
            key="hygiene-report",
            version=1,
            title="Hygiene Bericht",
            status=Form.PublicationStatus.PUBLISHED,
            published_at=timezone.now(),
            created_by=self.user,
            updated_by=self.user,
        )
        self.name_field = Field.objects.create(
            form=self.form,
            key="bereich",
            label="Bereich",
            field_type=Field.FieldType.TEXT,
            position=1,
            created_by=self.user,
            updated_by=self.user,
        )
        self.ok_field = Field.objects.create(
            form=self.form,
            key="ok",
            label="OK",
            field_type=Field.FieldType.BOOLEAN,
            position=2,
            created_by=self.user,
            updated_by=self.user,
        )
        self.form.schema = self.form.build_schema()
        self.form.save(update_fields=["schema"])
        self.bewohner = Bewohner.objects.create(
            resident_number="R-900",
            first_name="Max",
            last_name="Muster",
            created_by=self.user,
            updated_by=self.user,
        )
        self.entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            status=FormEntry.EntryStatus.IN_REVIEW,
            form_snapshot=self.form.schema,
            data={"bereich": "Kueche", "ok": False},
            submitted_at=timezone.now(),
            created_by=self.user,
            updated_by=self.user,
        )

    def test_excel_export_contains_entry_values(self):
        data = export_entries_to_xlsx(user=self.user, entries=FormEntry.objects.filter(pk=self.entry.pk))
        workbook = load_workbook(BytesIO(data))
        sheet = workbook["Eintraege"]
        headers = [cell.value for cell in sheet[1]]
        values = [cell.value for cell in sheet[2]]
        self.assertIn("Bereich", headers)
        self.assertIn("Kueche", values)
        self.assertIn("Nein", values)

    def test_operational_dashboard_counts_scoped_work_items(self):
        ActionItem.objects.create(
            source_entry=self.entry,
            title="Massnahme",
            status=ActionItem.Status.OPEN,
            due_at=timezone.now() - timezone.timedelta(days=1),
            created_by=self.user,
            updated_by=self.user,
        )
        data = get_operational_dashboard_data(self.user)
        self.assertEqual(data["counts"]["pending_reviews"], 1)
        self.assertEqual(data["counts"]["overdue_action_items"], 1)

    def test_monthly_pdf_report_is_generated(self):
        ActionItem.objects.create(
            source_entry=self.entry,
            title="Kritische Massnahme",
            priority=ActionItem.Priority.HIGH,
            status=ActionItem.Status.OPEN,
            due_at=timezone.now() - timezone.timedelta(days=1),
            created_by=self.user,
            updated_by=self.user,
        )
        pdf = render_monthly_report_pdf(user=self.user, form=self.form, period=None)  # type: ignore[arg-type]
        self.assertTrue(pdf.startswith(b"%PDF"))
