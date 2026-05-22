from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from form_builder.audit_services import audit_download, audit_permission_denied
from form_builder.models import AuditLog, Bewohner, Form, FormEntry, PDFDocument, SentFormArchive
from form_builder.permissions import can_apply_retention_policy, can_export_entries, can_view_entry
from form_builder.retention_services import apply_retention_policy


class AuditRetentionPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin", password="test", is_staff=True, is_superuser=True
        )
        self.viewer = User.objects.create_user(username="viewer", password="test")
        self.form = Form.objects.create(
            key="retention-test",
            version=1,
            title="Retention Test",
            status=Form.PublicationStatus.DRAFT,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.bewohner = Bewohner.objects.create(
            resident_number="RET-1",
            first_name="Max",
            last_name="Muster",
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            status=FormEntry.EntryStatus.ARCHIVED,
            data={"name": "Max Muster", "note": "Sensitive"},
            form_snapshot={"fields": []},
            archived_at=timezone.now() - timedelta(days=10),
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.pdf = PDFDocument.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            document_kind=PDFDocument.DocumentKind.FINAL,
            status=PDFDocument.GenerationStatus.GENERATED,
            storage_key="test/final.pdf",
            original_filename="final.pdf",
            file_size=12,
            sha256="abc",
            generated_at=timezone.now(),
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.archive = SentFormArchive.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            pdf_document=self.pdf,
            sent_at=timezone.now() - timedelta(days=20),
            retention_until=timezone.now() - timedelta(days=1),
            created_by=self.admin,
            updated_by=self.admin,
        )

    def test_audit_helpers_preserve_hash_chain(self):
        request = RequestFactory().get("/download", HTTP_USER_AGENT="pytest")
        first = audit_download(
            actor=self.admin,
            target_model="PDFDocument",
            target_id=self.pdf.pk,
            bewohner=self.bewohner,
            form=self.form,
            form_entry=self.entry,
            request=request,
            metadata={"scope": "test"},
        )
        second = audit_permission_denied(
            actor=self.viewer,
            target_model="FormEntry",
            target_id=self.entry.pk,
            action="view",
            bewohner=self.bewohner,
            form=self.form,
            form_entry=self.entry,
            request=request,
        )
        self.assertEqual(first.event_type, AuditLog.EventType.DOWNLOAD)
        self.assertEqual(second.previous_hash, first.entry_hash)
        self.assertEqual(second.metadata["action"], "view")

    def test_retention_dry_run_does_not_change_entry(self):
        result = apply_retention_policy(actor=self.admin, dry_run=True)
        self.assertEqual(result.eligible, 1)
        self.assertEqual(result.processed, 0)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.data["name"], "Max Muster")

    def test_retention_apply_anonymizes_entry_and_audits(self):
        result = apply_retention_policy(actor=self.admin, dry_run=False)
        self.assertEqual(result.processed, 1)
        self.entry.refresh_from_db()
        self.archive.refresh_from_db()
        self.assertEqual(self.entry.status, FormEntry.EntryStatus.DELETED)
        self.assertEqual(self.entry.data, {})
        self.assertEqual(self.archive.archive_metadata["retention"]["status"], "processed")
        self.assertTrue(
            AuditLog.objects.filter(
                target_model="SentFormArchive",
                target_id=self.archive.pk,
                event_type=AuditLog.EventType.DELETED,
            ).exists()
        )

    def test_export_and_retention_permissions_are_staff_only(self):
        self.assertTrue(can_export_entries(self.admin))
        self.assertTrue(can_apply_retention_policy(self.admin))
        self.assertFalse(can_export_entries(self.viewer))
        self.assertFalse(can_apply_retention_policy(self.viewer))
        self.assertFalse(can_view_entry(self.viewer, self.entry))
