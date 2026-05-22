import base64

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from form_builder.attachment_models import FormEntryAttachment
from form_builder.models import Bewohner, Field, Form, FormEntry
from form_builder.services import build_entry_form, create_form_entry_from_validated, submit_draft_for_review


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@override_settings(DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage")
class AttachmentAndSignatureTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="staff", password="test", is_staff=True)
        self.other = User.objects.create_user(username="other", password="test")
        self.bewohner = Bewohner.objects.create(
            resident_number="R-1",
            first_name="Max",
            last_name="Muster",
            created_by=self.user,
            updated_by=self.user,
        )
        self.form = Form.objects.create(
            key="hygiene-report",
            version=1,
            title="Hygiene Report",
            status=Form.PublicationStatus.DRAFT,
            created_by=self.user,
            updated_by=self.user,
        )
        Field.objects.create(
            form=self.form,
            key="photo",
            label="Foto",
            field_type=Field.FieldType.FILE,
            position=1,
            required=True,
            validation_rules={"allowed_content_types": ["image/png"], "max_size_mb": 2},
            ui_config={"accept": "image/*", "capture": "environment"},
            created_by=self.user,
            updated_by=self.user,
        )
        Field.objects.create(
            form=self.form,
            key="signature",
            label="Unterschrift",
            field_type=Field.FieldType.TEXT,
            position=2,
            required=True,
            ui_config={"widget": "signature"},
            created_by=self.user,
            updated_by=self.user,
        )
        self.form.sync_schema()
        self.form.publish()
        self.form.sync_schema()

    def _signature_data_url(self):
        return "data:image/png;base64," + base64.b64encode(PNG_1X1).decode("ascii")

    def test_file_upload_creates_private_attachment_metadata(self):
        upload = SimpleUploadedFile("defect.png", PNG_1X1, content_type="image/png")
        form = build_entry_form(
            self.form,
            data={"signature": self._signature_data_url()},
            files={"photo": upload},
        )
        self.assertTrue(form.is_valid(), form.errors)
        entry = create_form_entry_from_validated(
            form_definition=self.form,
            bewohner=self.bewohner,
            cleaned_data=form.cleaned_data,
            uploaded_files={"photo": upload},
            user=self.user,
        )
        attachment = FormEntryAttachment.objects.get(entry=entry, field_key="photo")
        self.assertEqual(attachment.original_filename, "defect.png")
        self.assertEqual(attachment.content_type, "image/png")
        self.assertEqual(len(attachment.sha256), 64)
        self.assertIn("photo", entry.data)

    def test_invalid_content_type_is_rejected(self):
        upload = SimpleUploadedFile("script.txt", b"bad", content_type="text/plain")
        form = build_entry_form(
            self.form,
            data={"signature": self._signature_data_url()},
            files={"photo": upload},
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaisesMessage(Exception, "Dateityp"):
            create_form_entry_from_validated(
                form_definition=self.form,
                bewohner=self.bewohner,
                cleaned_data=form.cleaned_data,
                uploaded_files={"photo": upload},
                user=self.user,
            )

    def test_signature_is_stored_as_auditable_attachment_and_locked_after_submit(self):
        upload = SimpleUploadedFile("defect.png", PNG_1X1, content_type="image/png")
        form = build_entry_form(
            self.form,
            data={"signature": self._signature_data_url()},
            files={"photo": upload},
        )
        self.assertTrue(form.is_valid(), form.errors)
        entry = create_form_entry_from_validated(
            form_definition=self.form,
            bewohner=self.bewohner,
            cleaned_data=form.cleaned_data,
            uploaded_files={"photo": upload},
            user=self.user,
        )
        signature = FormEntryAttachment.objects.get(entry=entry, field_key="signature")
        self.assertEqual(signature.kind, FormEntryAttachment.AttachmentKind.SIGNATURE)
        self.assertEqual(len(signature.signature_hash), 64)
        submit_draft_for_review(
            entry,
            cleaned_data={"signature": entry.data["signature"]},
            user=self.user,
        )
        self.assertEqual(entry.status, FormEntry.EntryStatus.IN_REVIEW)

    def test_unauthorized_attachment_download_is_denied(self):
        upload = SimpleUploadedFile("defect.png", PNG_1X1, content_type="image/png")
        form = build_entry_form(
            self.form,
            data={"signature": self._signature_data_url()},
            files={"photo": upload},
        )
        self.assertTrue(form.is_valid(), form.errors)
        entry = create_form_entry_from_validated(
            form_definition=self.form,
            bewohner=self.bewohner,
            cleaned_data=form.cleaned_data,
            uploaded_files={"photo": upload},
            user=self.user,
        )
        attachment = FormEntryAttachment.objects.get(entry=entry, field_key="photo")
        self.client.force_login(self.other)
        response = self.client.get(reverse("form_builder:attachment_download", args=[attachment.pk]))
        self.assertEqual(response.status_code, 403)
