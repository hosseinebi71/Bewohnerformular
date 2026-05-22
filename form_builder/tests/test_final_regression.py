from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from form_builder.attachment_models import FormEntryAttachment
from form_builder.models import Bewohner, Field, Form, FormEntry, UserAccessProfile


@override_settings(MEDIA_ROOT=None)
class FinalRegressionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user("admin", password="test", is_staff=True, is_superuser=True)
        self.limited = User.objects.create_user("limited", password="test", is_staff=True)
        self.form = Form.objects.create(
            key="regression-form",
            version=1,
            title="Regression Form",
            status=Form.PublicationStatus.PUBLISHED,
            org_unit="west",
            created_by=self.admin,
            updated_by=self.admin,
        )
        Field.objects.create(
            form=self.form,
            key="name",
            label="Name",
            field_type=Field.FieldType.TEXT,
            position=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.form.sync_schema()
        self.resident = Bewohner.objects.create(
            resident_number="R-1",
            first_name="Max",
            last_name="Muster",
            org_unit="west",
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.resident,
            form_snapshot=self.form.schema,
            data={"name": "Max"},
            created_by=self.admin,
            updated_by=self.admin,
        )

    def test_core_routes_resolve_for_admin(self):
        self.client.force_login(self.admin)
        for name in [
            "form_builder:dashboard",
            "form_builder:operational_dashboard",
            "form_builder:form_list",
            "form_builder:form_template_list",
        ]:
            response = self.client.get(reverse(name))
            self.assertLess(response.status_code, 500, name)

    def test_scoped_user_cannot_view_other_org_entry(self):
        UserAccessProfile.objects.create(
            user=self.limited,
            scope_mode=UserAccessProfile.ScopeMode.ORG_UNITS,
            org_units=["east"],
            can_dashboard=True,
            can_forms=True,
            can_create=True,
            can_send=False,
            can_archive=True,
            can_settings=False,
            can_manage_settings=False,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.client.force_login(self.limited)
        response = self.client.get(reverse("form_builder:entry_detail", args=[self.entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_attachment_download_uses_entry_permission_scope(self):
        upload = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        attachment = FormEntryAttachment.objects.create(
            entry=self.entry,
            field_key="name",
            original_filename="note.txt",
            file=upload,
            content_type="text/plain",
            file_size=5,
            sha256="0" * 64,
            created_by=self.admin,
            updated_by=self.admin,
        )
        UserAccessProfile.objects.create(
            user=self.limited,
            scope_mode=UserAccessProfile.ScopeMode.ORG_UNITS,
            org_units=["east"],
            can_dashboard=True,
            can_forms=True,
            can_create=True,
            can_send=False,
            can_archive=True,
            can_settings=False,
            can_manage_settings=False,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.client.force_login(self.limited)
        response = self.client.get(reverse("form_builder:attachment_download", args=[attachment.pk]))
        self.assertEqual(response.status_code, 403)
