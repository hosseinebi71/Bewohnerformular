from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from pypdf import PdfReader

from form_builder.models import Bewohner, Field, Form, FormEntry
from form_builder.pdf_template_models import PDFTemplatePlacement
from form_builder.pdf_template_services import (
    create_pdf_template_from_upload,
    render_from_template_if_available,
    render_pdf_template_bytes,
)


def make_pdf_bytes(text="Template"):
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(300, 200))
    c.drawString(20, 180, text)
    c.save()
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=None)
class PDFTemplateTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.tmp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        User = get_user_model()
        self.user = User.objects.create_user("admin", password="test", is_staff=True)
        self.form = Form.objects.create(
            key="pdf-template-test",
            version=1,
            title="PDF Template Test",
            status=Form.PublicationStatus.DRAFT,
            created_by=self.user,
            updated_by=self.user,
        )
        self.name_field = Field.objects.create(
            form=self.form,
            key="name",
            label="Name",
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
        self.form.sync_schema()
        self.bewohner = Bewohner.objects.create(
            resident_number="P-1",
            first_name="Max",
            last_name="Muster",
            created_by=self.user,
            updated_by=self.user,
        )

    def _upload_template(self):
        uploaded = SimpleUploadedFile(
            "template.pdf",
            make_pdf_bytes(),
            content_type="application/pdf",
        )
        return create_pdf_template_from_upload(
            form=self.form,
            uploaded_file=uploaded,
            user=self.user,
            name="Testvorlage",
        )

    def test_pdf_upload_stores_page_metadata(self):
        template = self._upload_template()
        self.assertEqual(template.page_count, 1)
        self.assertEqual(template.page_metadata[0]["page_number"], 1)
        self.assertEqual(template.content_type, "application/pdf")
        self.assertTrue(Path(template.file.path).exists())

    def test_rejects_non_pdf_upload(self):
        uploaded = SimpleUploadedFile("template.txt", b"not a pdf", content_type="text/plain")
        with self.assertRaises(ValidationError):
            create_pdf_template_from_upload(
                form=self.form,
                uploaded_file=uploaded,
                user=self.user,
                name="Bad",
            )

    def test_placement_validation_checks_page_and_coordinates(self):
        template = self._upload_template()
        placement = PDFTemplatePlacement(
            template=template,
            field=self.name_field,
            page_number=2,
            x=0.1,
            y=0.1,
            width=0.2,
            height=0.05,
        )
        with self.assertRaises(ValidationError):
            placement.full_clean()

    def test_render_text_and_checkbox_placements(self):
        template = self._upload_template()
        template.status = template.TemplateStatus.ACTIVE
        template.save(update_fields=["status"])
        PDFTemplatePlacement.objects.create(
            template=template,
            field=self.name_field,
            page_number=1,
            x=0.1,
            y=0.2,
            width=0.5,
            height=0.08,
            kind=PDFTemplatePlacement.PlacementKind.TEXT,
            created_by=self.user,
            updated_by=self.user,
        )
        PDFTemplatePlacement.objects.create(
            template=template,
            field=self.ok_field,
            page_number=1,
            x=0.1,
            y=0.35,
            width=0.08,
            height=0.08,
            kind=PDFTemplatePlacement.PlacementKind.CHECKBOX,
            created_by=self.user,
            updated_by=self.user,
        )
        entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            form_snapshot=self.form.schema,
            data={"name": "Max Muster", "ok": True},
            created_by=self.user,
            updated_by=self.user,
        )
        pdf_bytes = render_pdf_template_bytes(form_entry=entry, template=template)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        reader = PdfReader(BytesIO(pdf_bytes))
        self.assertEqual(len(reader.pages), 1)
        self.assertIsNotNone(render_from_template_if_available(form_entry=entry))
