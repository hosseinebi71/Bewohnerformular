from django.contrib.auth import get_user_model
from django.test import TestCase

from form_builder import pdf_services, services
from form_builder.models import Bewohner, Form, FormEntry
from form_builder.selectors import get_dashboard_counts, get_user_drafts_queryset


class SelectorAndServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create(username="staff", is_staff=True)
        self.user_a = User.objects.create(username="user_a")
        self.user_b = User.objects.create(username="user_b")
        self.bewohner = Bewohner.objects.create(
            resident_number="TEST-001",
            first_name="Test",
            last_name="Bewohner",
        )
        self.form = Form.objects.create(key="test-form", version=1, title="Test Form")

    def _entry(self, *, status, created_by):
        return FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            status=status,
            form_snapshot={"fields": []},
            data={},
            created_by=created_by,
            updated_by=created_by,
        )

    def test_dashboard_review_count_uses_real_queryset(self):
        self._entry(status=FormEntry.EntryStatus.IN_REVIEW, created_by=self.user_a)
        counts = get_dashboard_counts(self.staff)
        self.assertEqual(counts["in_review"], 1)

    def test_drafts_queryset_filters_normal_users_but_not_staff(self):
        own = self._entry(status=FormEntry.EntryStatus.DRAFT, created_by=self.user_a)
        other = self._entry(status=FormEntry.EntryStatus.DRAFT, created_by=self.user_b)

        self.assertEqual(list(get_user_drafts_queryset(self.user_a)), [own])
        self.assertCountEqual(list(get_user_drafts_queryset(self.staff)), [own, other])

    def test_latest_pdf_helper_has_single_source_of_truth(self):
        self.assertIs(
            services.get_latest_generated_pdf_document,
            pdf_services.get_latest_generated_pdf_document,
        )


from django.contrib.auth.models import Group

from form_builder.models import PDFDocument
from form_builder.permissions import VIEWER_GROUP, can_view_entry, can_view_pdf_document


class ObjectPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer_group = Group.objects.create(name=VIEWER_GROUP)
        self.owner = User.objects.create(username="owner")
        self.owner.groups.add(self.viewer_group)
        self.other = User.objects.create(username="other")
        self.other.groups.add(self.viewer_group)
        self.staff = User.objects.create(username="staff2", is_staff=True)
        self.bewohner = Bewohner.objects.create(
            resident_number="PERM-001",
            first_name="Perm",
            last_name="Bewohner",
        )
        self.form = Form.objects.create(key="perm-form", version=1, title="Permission Form")
        self.entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            status=FormEntry.EntryStatus.DRAFT,
            form_snapshot={"fields": []},
            data={},
            created_by=self.owner,
            updated_by=self.owner,
        )

    def test_object_permissions_allow_owner_and_staff_not_other_viewer(self):
        self.assertTrue(can_view_entry(self.owner, self.entry))
        self.assertTrue(can_view_entry(self.staff, self.entry))
        self.assertFalse(can_view_entry(self.other, self.entry))

    def test_pdf_permission_follows_entry_permission(self):
        pdf = PDFDocument.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            status=PDFDocument.GenerationStatus.GENERATED,
            storage_key="pdf_documents/test.pdf",
            original_filename="test.pdf",
            created_by=self.owner,
            updated_by=self.owner,
        )
        self.assertTrue(can_view_pdf_document(self.owner, pdf))
        self.assertFalse(can_view_pdf_document(self.other, pdf))

    def test_selectors_include_updated_entries_for_non_staff_users(self):
        self.entry.created_by = self.other
        self.entry.updated_by = self.owner
        self.entry.save(update_fields=["created_by", "updated_by", "updated_at"])
        self.assertIn(self.entry, list(get_user_drafts_queryset(self.owner)))
