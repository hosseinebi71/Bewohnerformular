from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from form_builder.models import Bewohner, Field, Form, FormEntry
from form_builder.qr_context_models import QRFormContext
from form_builder.qr_context_services import create_entry_from_qr_context, render_qr_png


class QRContextTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("staff", password="test", is_staff=True)
        self.form = Form.objects.create(
            key="hygiene-qr",
            version=1,
            title="Hygiene QR",
            status=Form.PublicationStatus.DRAFT,
            created_by=self.user,
            updated_by=self.user,
        )
        Field.objects.create(
            form=self.form,
            key="bereich",
            label="Bereich",
            field_type=Field.FieldType.TEXT,
            position=1,
            created_by=self.user,
            updated_by=self.user,
        )
        self.form.publish()
        self.form.refresh_from_db()
        self.form.sync_schema()
        self.bewohner = Bewohner.objects.create(
            resident_number="QR-1",
            first_name="Max",
            last_name="Muster",
            room_label="A-12",
            created_by=self.user,
            updated_by=self.user,
        )

    def test_qr_token_creates_prefilled_draft_entry(self):
        context = QRFormContext.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            label="Kueche 1",
            context_type="room",
            context_key="kueche-1",
            context_payload={"bereich": "Kueche"},
            created_by=self.user,
            updated_by=self.user,
        )
        entry = create_entry_from_qr_context(context=context, user=self.user)
        self.assertEqual(entry.status, FormEntry.EntryStatus.DRAFT)
        self.assertEqual(entry.bewohner, self.bewohner)
        self.assertEqual(entry.data["bereich"], "Kueche")
        context.refresh_from_db()
        self.assertEqual(context.usage_count, 1)

    def test_qr_png_generation_returns_png_bytes(self):
        image = render_qr_png("https://example.invalid/qr/token")
        self.assertTrue(image.startswith(b"\x89PNG"))

    def test_qr_open_view_redirects_to_entry_edit(self):
        context = QRFormContext.objects.create(
            form=self.form,
            label="Station A",
            context_type="location",
            context_key="station-a",
            context_payload={"bereich": "Station A"},
            created_by=self.user,
            updated_by=self.user,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("form_builder:qr_context_open", kwargs={"token": context.token})
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(FormEntry.objects.filter(form=self.form).count(), 1)
