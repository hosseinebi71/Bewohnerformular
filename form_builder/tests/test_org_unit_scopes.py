from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from form_builder.models import (
    Bewohner,
    Form,
    FormEntry,
    FormRecipient,
    OutboxItem,
    PDFDocument,
    SentFormArchive,
    UserAccessProfile,
)
from form_builder.permissions import (
    VIEWER_GROUP,
    can_view_entry,
    can_view_form,
    can_view_pdf_document,
    entry_scope_q,
    form_scope_q,
)
from form_builder.selectors import (
    get_archive_queryset,
    get_available_forms_queryset,
    get_dashboard_counts,
    get_entries_in_review_queryset,
    get_outbox_pending_queryset,
    get_recent_activity,
    get_sent_outbox_queryset,
    get_user_drafts_queryset,
)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OrgUnitScopeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer_group = Group.objects.create(name=VIEWER_GROUP)
        self.owner = User.objects.create_user(username="owner_scope", password="pass")
        self.owner.groups.add(self.viewer_group)
        self.viewer = User.objects.create_user(username="viewer_scope", password="pass")
        self.viewer.groups.add(self.viewer_group)
        self.other_viewer = User.objects.create_user(username="other_scope", password="pass")
        self.other_viewer.groups.add(self.viewer_group)
        self.staff = User.objects.create_user(
            username="staff_scope", password="pass", is_staff=True
        )
        self.admin = User.objects.create_user(
            username="admin_scope", password="pass", is_superuser=True
        )

        self.form_a = Form.objects.create(
            key="form-a",
            version=1,
            title="Form A",
            org_unit="weeze",
            status=Form.PublicationStatus.PUBLISHED,
            published_at=timezone.now(),
            schema={"fields": []},
        )
        self.form_b = Form.objects.create(
            key="form-b",
            version=1,
            title="Form B",
            org_unit="duesseldorf",
            status=Form.PublicationStatus.PUBLISHED,
            published_at=timezone.now(),
            schema={"fields": []},
        )
        self.form_blank = Form.objects.create(
            key="form-blank",
            version=1,
            title="Blank",
            org_unit="",
            status=Form.PublicationStatus.PUBLISHED,
            published_at=timezone.now(),
            schema={"fields": []},
        )
        self.bewohner_a = Bewohner.objects.create(
            resident_number="OU-001", first_name="A", last_name="Resident", org_unit="weeze"
        )
        self.bewohner_b = Bewohner.objects.create(
            resident_number="OU-002", first_name="B", last_name="Resident", org_unit="duesseldorf"
        )
        self.entry_a = FormEntry.objects.create(
            form=self.form_a,
            bewohner=self.bewohner_a,
            status=FormEntry.EntryStatus.DRAFT,
            form_snapshot={"fields": []},
            data={},
            created_by=self.owner,
            updated_by=self.owner,
        )
        self.entry_b = FormEntry.objects.create(
            form=self.form_b,
            bewohner=self.bewohner_b,
            status=FormEntry.EntryStatus.DRAFT,
            form_snapshot={"fields": []},
            data={},
            created_by=self.other_viewer,
            updated_by=self.other_viewer,
        )
        self.entry_mixed = FormEntry.objects.create(
            form=self.form_b,
            bewohner=self.bewohner_a,
            status=FormEntry.EntryStatus.IN_REVIEW,
            form_snapshot={"fields": []},
            data={},
            created_by=self.other_viewer,
            updated_by=self.other_viewer,
        )
        self.recipient = FormRecipient.objects.create(form=self.form_a, email="scope@example.com")

    def profile(self, user, *, mode="org_units", org_units=None, form_keys=None, **flags):
        defaults = {
            "can_dashboard": True,
            "can_forms": True,
            "can_create": False,
            "can_send": False,
            "can_archive": True,
            "scope_mode": mode,
            "org_units": org_units if org_units is not None else ["weeze"],
            "allowed_form_keys": form_keys if form_keys is not None else [],
        }
        defaults.update(flags)
        return UserAccessProfile.objects.create(user=user, **defaults)

    def test_org_unit_profile_can_view_entries_in_same_resident_or_form_scope(self):
        self.profile(self.viewer, org_units=["weeze"])
        self.assertTrue(can_view_entry(self.viewer, self.entry_a))
        self.assertTrue(can_view_entry(self.viewer, self.entry_mixed))
        self.assertFalse(can_view_entry(self.viewer, self.entry_b))

    def test_org_unit_profile_filters_drafts_queryset(self):
        self.profile(self.viewer, org_units=["weeze"])
        self.assertCountEqual(list(get_user_drafts_queryset(self.viewer)), [self.entry_a])

    def test_org_unit_profile_filters_review_queryset(self):
        self.profile(self.viewer, org_units=["weeze"])
        self.assertEqual(list(get_entries_in_review_queryset(self.viewer)), [self.entry_mixed])

    def test_allowed_form_keys_restrict_entry_scope_even_when_org_matches(self):
        self.profile(self.viewer, org_units=["weeze"], form_keys=["form-a"])
        self.assertTrue(can_view_entry(self.viewer, self.entry_a))
        self.assertFalse(can_view_entry(self.viewer, self.entry_mixed))

    def test_allowed_form_keys_restrict_available_forms(self):
        self.profile(self.viewer, org_units=["weeze", "duesseldorf"], form_keys=["form-a"])
        self.assertEqual(list(get_available_forms_queryset(self.viewer)), [self.form_a])

    def test_org_unit_profile_rejects_unscoped_blank_forms(self):
        self.profile(self.viewer, org_units=["weeze"])
        self.assertNotIn(self.form_blank, list(get_available_forms_queryset(self.viewer)))
        self.assertFalse(can_view_form(self.viewer, self.form_blank))

    def test_own_scope_keeps_owner_access_but_blocks_same_org_non_owner(self):
        self.profile(self.viewer, mode="own", org_units=["weeze"])
        self.assertFalse(can_view_entry(self.viewer, self.entry_a))
        self.entry_a.updated_by = self.viewer
        self.entry_a.save(update_fields=["updated_by", "updated_at"])
        self.assertTrue(can_view_entry(self.viewer, self.entry_a))

    def test_all_scope_with_allowed_form_keys_limits_forms_and_entries(self):
        self.profile(self.viewer, mode="all", org_units=[], form_keys=["form-a"])
        self.assertTrue(can_view_entry(self.viewer, self.entry_a))
        self.assertFalse(can_view_entry(self.viewer, self.entry_b))
        self.assertEqual(list(get_available_forms_queryset(self.viewer)), [self.form_a])

    def test_legacy_staff_without_profile_keeps_full_scope(self):
        self.assertTrue(can_view_entry(self.staff, self.entry_b))
        self.assertCountEqual(
            list(get_user_drafts_queryset(self.staff)), [self.entry_a, self.entry_b]
        )

    def test_staff_with_profile_can_be_restricted_to_org_unit(self):
        self.profile(self.staff, org_units=["weeze"], can_create=True, can_send=True)
        self.assertTrue(can_view_entry(self.staff, self.entry_a))
        self.assertFalse(can_view_entry(self.staff, self.entry_b))
        self.assertEqual(list(get_user_drafts_queryset(self.staff)), [self.entry_a])

    def test_admin_is_not_restricted_by_profile_scope(self):
        self.profile(self.admin, org_units=["weeze"], form_keys=["form-a"])
        self.assertTrue(can_view_entry(self.admin, self.entry_b))
        self.assertCountEqual(
            list(get_available_forms_queryset(self.admin)),
            [self.form_a, self.form_b, self.form_blank],
        )

    def test_outbox_pending_queryset_uses_org_scope(self):
        self.profile(self.viewer, org_units=["weeze"])
        recipient_b = FormRecipient.objects.create(form=self.form_b, email="scope-b@example.com")
        own = OutboxItem.objects.create(
            form=self.form_a,
            form_entry=self.entry_a,
            bewohner=self.bewohner_a,
            recipient=self.recipient,
            subject="own",
        )
        other = OutboxItem.objects.create(
            form=self.form_b,
            form_entry=self.entry_b,
            bewohner=self.bewohner_b,
            recipient=recipient_b,
            subject="other",
        )
        self.assertEqual(list(get_outbox_pending_queryset(self.viewer)), [own])
        self.assertIn(other, list(get_outbox_pending_queryset(self.admin)))

    def test_sent_and_archive_queryset_use_org_scope(self):
        self.profile(self.viewer, org_units=["weeze"])
        recipient_b = FormRecipient.objects.create(form=self.form_b, email="scope-b2@example.com")
        sent_own = OutboxItem.objects.create(
            form=self.form_a,
            form_entry=self.entry_a,
            bewohner=self.bewohner_a,
            recipient=self.recipient,
            status=OutboxItem.DeliveryStatus.SENT,
            subject="own",
        )
        OutboxItem.objects.create(
            form=self.form_b,
            form_entry=self.entry_b,
            bewohner=self.bewohner_b,
            recipient=recipient_b,
            status=OutboxItem.DeliveryStatus.SENT,
            subject="other",
        )
        pdf_own = PDFDocument.objects.create(
            form=self.form_a,
            form_entry=self.entry_a,
            bewohner=self.bewohner_a,
            status=PDFDocument.GenerationStatus.GENERATED,
            storage_key="pdf_documents/scope/a.pdf",
            original_filename="a.pdf",
        )
        PDFDocument.objects.create(
            form=self.form_b,
            form_entry=self.entry_b,
            bewohner=self.bewohner_b,
            status=PDFDocument.GenerationStatus.GENERATED,
            storage_key="pdf_documents/scope/b.pdf",
            original_filename="b.pdf",
        )
        archive_own = SentFormArchive.objects.create(
            form=self.form_a,
            form_entry=self.entry_a,
            bewohner=self.bewohner_a,
            pdf_document=pdf_own,
            sent_at=timezone.now(),
        )
        self.assertEqual(list(get_sent_outbox_queryset(self.viewer)), [sent_own])
        self.assertEqual(list(get_archive_queryset(self.viewer)), [archive_own])

    def test_recent_activity_uses_org_scope(self):
        self.profile(self.viewer, org_units=["weeze"])
        activity = get_recent_activity(user=self.viewer)
        self.assertIn(self.entry_a, list(activity["entries"]))
        self.assertNotIn(self.entry_b, list(activity["entries"]))

    def test_pdf_permission_uses_org_scope(self):
        self.profile(self.viewer, org_units=["weeze"])
        pdf_a = PDFDocument.objects.create(
            form=self.form_a,
            form_entry=self.entry_a,
            bewohner=self.bewohner_a,
            status=PDFDocument.GenerationStatus.GENERATED,
            storage_key="pdf_documents/scope/a.pdf",
            original_filename="a.pdf",
        )
        pdf_b = PDFDocument.objects.create(
            form=self.form_b,
            form_entry=self.entry_b,
            bewohner=self.bewohner_b,
            status=PDFDocument.GenerationStatus.GENERATED,
            storage_key="pdf_documents/scope/b.pdf",
            original_filename="b.pdf",
        )
        self.assertTrue(can_view_pdf_document(self.viewer, pdf_a))
        self.assertFalse(can_view_pdf_document(self.viewer, pdf_b))

    def test_entry_detail_view_respects_org_scope(self):
        self.profile(self.viewer, org_units=["weeze"])
        self.client.login(username="viewer_scope", password="pass")
        self.assertEqual(
            self.client.get(
                reverse("form_builder:entry_detail", args=[self.entry_a.pk])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("form_builder:entry_detail", args=[self.entry_b.pk])
            ).status_code,
            403,
        )

    def test_form_list_view_respects_available_form_scope(self):
        self.profile(self.viewer, org_units=["weeze"], form_keys=["form-a"])
        self.client.login(username="viewer_scope", password="pass")
        response = self.client.get(reverse("form_builder:form_list"))
        self.assertEqual(response.status_code, 200)
        forms = list(response.context["forms"])
        self.assertEqual(forms, [self.form_a])

    def test_dashboard_counts_respect_org_scope(self):
        self.profile(self.viewer, org_units=["weeze"])
        counts = get_dashboard_counts(self.viewer)
        self.assertEqual(counts["drafts"], 1)
        self.assertEqual(counts["in_review"], 1)
        self.assertEqual(counts["available_forms"], 1)

    def test_profile_with_empty_org_units_matches_no_entries_in_org_mode(self):
        self.profile(self.viewer, org_units=[])
        self.assertEqual(list(get_user_drafts_queryset(self.viewer)), [])
        self.assertFalse(can_view_entry(self.viewer, self.entry_a))

    def test_entry_scope_q_matches_can_view_entry(self):
        self.profile(self.viewer, org_units=["weeze"], form_keys=["form-a"])
        scoped = set(
            FormEntry.objects.filter(entry_scope_q(self.viewer)).values_list("pk", flat=True)
        )
        self.assertEqual(scoped, {self.entry_a.pk})

    def test_form_scope_q_matches_available_forms(self):
        self.profile(self.viewer, org_units=["duesseldorf"])
        scoped = set(
            Form.objects.filter(
                form_scope_q(self.viewer), status=Form.PublicationStatus.PUBLISHED
            ).values_list("pk", flat=True)
        )
        self.assertEqual(scoped, {self.form_b.pk})
