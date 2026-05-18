import io
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from form_builder.mail_services import (
    get_due_outbox_queryset,
    mark_outbox_failed,
    mark_outbox_sent,
    process_outbox_queue,
)
from form_builder.models import (
    AuditLog,
    Bewohner,
    Form,
    FormEntry,
    FormRecipient,
    FormSchedule,
    OutboxItem,
    PDFDocument,
    SentFormArchive,
)
from form_builder.pdf_services import get_pdf_private_path
from form_builder.permissions import VIEWER_GROUP, can_view_archive_record, can_view_outbox_item
from form_builder.schedule_services import compute_next_run_at
from form_builder.selectors import (
    get_archive_queryset,
    get_recent_activity,
    get_sent_outbox_queryset,
)
from form_builder.services import queue_entry_for_delivery


class SecurityFixtureMixin:
    def setUp(self):
        User = get_user_model()
        self.viewer_group = Group.objects.create(name=VIEWER_GROUP)
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.owner.groups.add(self.viewer_group)
        self.other = User.objects.create_user(username="other", password="pass")
        self.other.groups.add(self.viewer_group)
        self.staff = User.objects.create_user(username="staff", password="pass", is_staff=True)
        self.bewohner = Bewohner.objects.create(
            resident_number="SEC-001", first_name="Sec", last_name="Resident"
        )
        self.form = Form.objects.create(
            key="security-form",
            version=1,
            title="Security Form",
            status=Form.PublicationStatus.PUBLISHED,
            published_at=timezone.now(),
            schema={"fields": []},
        )
        self.entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            status=FormEntry.EntryStatus.DRAFT,
            form_snapshot={"fields": []},
            data={},
            created_by=self.owner,
            updated_by=self.owner,
        )

    def make_pdf(
        self,
        *,
        storage_key="pdf_documents/security/test.pdf",
        content=b"%PDF-1.4 test",
        document_kind=None,
    ):
        root = Path(tempfile.mkdtemp())
        with override_settings(PRIVATE_DOCUMENT_ROOT=root):
            pdf = PDFDocument.objects.create(
                form=self.form,
                form_entry=self.entry,
                bewohner=self.bewohner,
                document_kind=document_kind or PDFDocument.DocumentKind.REVIEW,
                status=PDFDocument.GenerationStatus.GENERATED,
                storage_key=storage_key,
                original_filename="test.pdf",
                content_type="application/pdf",
                file_size=len(content),
                sha256="0" * 64,
                generated_at=timezone.now(),
                created_by=self.owner,
                updated_by=self.owner,
            )
            path = get_pdf_private_path(pdf)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return root, pdf


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class AuditHashChainTests(SecurityFixtureMixin, TestCase):
    def test_audit_log_gets_hashes_on_create(self):
        log = AuditLog.objects.create(
            actor=self.owner,
            event_type=AuditLog.EventType.VIEWED,
            target_model="FormEntry",
            target_id=self.entry.pk,
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            message="Viewed for test.",
        )
        self.assertEqual(len(log.entry_hash), 64)
        self.assertEqual(log.entry_hash, log.calculate_entry_hash())

    def test_audit_log_chain_links_to_previous_hash(self):
        first = AuditLog.objects.create(
            actor=self.owner,
            event_type=AuditLog.EventType.CREATED,
            target_model="FormEntry",
            target_id=self.entry.pk,
        )
        second = AuditLog.objects.create(
            actor=self.owner,
            event_type=AuditLog.EventType.UPDATED,
            target_model="FormEntry",
            target_id=self.entry.pk,
        )
        self.assertEqual(second.previous_hash, first.entry_hash)

    def test_audit_log_is_append_only(self):
        log = AuditLog.objects.create(
            actor=self.owner,
            event_type=AuditLog.EventType.VIEWED,
            target_model="FormEntry",
            target_id=self.entry.pk,
        )
        log.message = "tampered"
        with self.assertRaises(ValidationError):
            log.save()

    def test_verify_audit_log_command_accepts_clean_chain(self):
        AuditLog.objects.create(
            actor=self.owner,
            event_type=AuditLog.EventType.CREATED,
            target_model="FormEntry",
            target_id=self.entry.pk,
        )
        out = io.StringIO()
        call_command("verify_audit_log", stdout=out)
        self.assertIn("AuditLog OK", out.getvalue())


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ObjectLevelViewTests(SecurityFixtureMixin, TestCase):
    def test_other_viewer_cannot_open_entry_detail(self):
        self.client.login(username="other", password="pass")
        response = self.client.get(reverse("form_builder:entry_detail", args=[self.entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_owner_can_open_entry_detail(self):
        self.client.login(username="owner", password="pass")
        response = self.client.get(reverse("form_builder:entry_detail", args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)

    def test_staff_can_open_entry_detail(self):
        self.client.login(username="staff", password="pass")
        response = self.client.get(reverse("form_builder:entry_detail", args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)

    def test_draft_entry_detail_does_not_show_send_action(self):
        self.client.login(username="staff", password="pass")
        response = self.client.get(reverse("form_builder:entry_detail", args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Jetzt schicken")

    def test_create_edit_and_draft_pages_do_not_show_direct_send_actions(self):
        self.client.login(username="staff", password="pass")

        create_response = self.client.get(reverse("form_builder:entry_create", args=[self.form.pk]))
        edit_response = self.client.get(reverse("form_builder:entry_edit", args=[self.entry.pk]))
        draft_response = self.client.get(reverse("form_builder:draft_list"))

        self.assertNotContains(create_response, "Sofort schicken")
        self.assertNotContains(edit_response, "Schicken")
        self.assertContains(edit_response, "In Review geben")
        self.assertNotContains(draft_response, "Jetzt schicken")

    def test_pdf_download_blocks_other_viewer(self):
        root, pdf = self.make_pdf()
        with override_settings(PRIVATE_DOCUMENT_ROOT=root):
            self.client.login(username="other", password="pass")
            response = self.client.get(reverse("form_builder:pdf_download", args=[pdf.pk]))
        self.assertEqual(response.status_code, 403)

    def test_pdf_download_allows_owner(self):
        root, pdf = self.make_pdf()
        with override_settings(PRIVATE_DOCUMENT_ROOT=root):
            self.client.login(username="owner", password="pass")
            response = self.client.get(reverse("form_builder:pdf_download", args=[pdf.pk]))
        self.assertEqual(response.status_code, 200)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SelectorScopeTests(SecurityFixtureMixin, TestCase):
    def test_sent_outbox_queryset_is_scoped_for_normal_user(self):
        recipient = FormRecipient.objects.create(form=self.form, email="case@example.com")
        own = OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient,
            status=OutboxItem.DeliveryStatus.SENT,
            subject="own",
        )
        other_entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            status=FormEntry.EntryStatus.DRAFT,
            form_snapshot={"fields": []},
            data={},
            created_by=self.other,
            updated_by=self.other,
        )
        other_item = OutboxItem.objects.create(
            form=self.form,
            form_entry=other_entry,
            bewohner=self.bewohner,
            recipient=recipient,
            status=OutboxItem.DeliveryStatus.SENT,
            subject="other",
        )
        self.assertEqual(
            list(get_sent_outbox_queryset(self.owner).values_list("pk", flat=True)), [own.pk]
        )
        self.assertEqual(
            set(get_sent_outbox_queryset(self.staff).values_list("pk", flat=True)),
            {own.pk, other_item.pk},
        )

    def test_archive_queryset_is_scoped_for_normal_user(self):
        root, pdf = self.make_pdf()
        archive = SentFormArchive.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            pdf_document=pdf,
            sent_at=timezone.now(),
        )
        self.assertEqual(list(get_archive_queryset(self.owner)), [archive])
        self.assertEqual(list(get_archive_queryset(self.other)), [])

    def test_recent_activity_includes_updated_entries_for_owner(self):
        self.entry.created_by = self.other
        self.entry.updated_by = self.owner
        self.entry.save(update_fields=["created_by", "updated_by", "updated_at"])
        activity = get_recent_activity(user=self.owner)
        self.assertIn(self.entry, list(activity["entries"]))

    def test_recent_activity_logs_are_scoped(self):
        own_log = AuditLog.objects.create(
            actor=self.owner,
            event_type=AuditLog.EventType.UPDATED,
            target_model="FormEntry",
            target_id=self.entry.pk,
            form_entry=self.entry,
        )
        other_entry = FormEntry.objects.create(
            form=self.form,
            bewohner=self.bewohner,
            status=FormEntry.EntryStatus.DRAFT,
            form_snapshot={"fields": []},
            data={},
            created_by=self.other,
            updated_by=self.other,
        )
        other_log = AuditLog.objects.create(
            actor=self.other,
            event_type=AuditLog.EventType.UPDATED,
            target_model="FormEntry",
            target_id=other_entry.pk,
            form_entry=other_entry,
        )
        logs = list(get_recent_activity(user=self.owner)["logs"])
        self.assertIn(own_log, logs)
        self.assertNotIn(other_log, logs)

    def test_outbox_and_archive_permission_helpers_reject_other_viewer(self):
        recipient = FormRecipient.objects.create(form=self.form, email="case2@example.com")
        item = OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient,
            subject="x",
        )
        root, pdf = self.make_pdf(storage_key="pdf_documents/security/archive.pdf")
        archive = SentFormArchive.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            pdf_document=pdf,
            sent_at=timezone.now(),
        )
        self.assertTrue(can_view_outbox_item(self.owner, item))
        self.assertFalse(can_view_outbox_item(self.other, item))
        self.assertTrue(can_view_archive_record(self.owner, archive))
        self.assertFalse(can_view_archive_record(self.other, archive))


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OutboxAndRetentionTests(SecurityFixtureMixin, TestCase):
    def test_due_outbox_queryset_includes_null_and_past_but_not_future(self):
        recipient = FormRecipient.objects.create(form=self.form, email="due@example.com")
        null_due = OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient,
            subject="null",
            next_attempt_at=None,
        )
        past_due = OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient,
            subject="past",
            next_attempt_at=timezone.now() - timedelta(minutes=1),
        )
        OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient,
            subject="future",
            next_attempt_at=timezone.now() + timedelta(hours=1),
        )
        self.assertCountEqual(list(get_due_outbox_queryset()), [null_due, past_due])

    def test_queue_rejects_non_approved_entries(self):
        FormRecipient.objects.create(form=self.form, email="draft@example.com")

        for status in [
            FormEntry.EntryStatus.DRAFT,
            FormEntry.EntryStatus.REJECTED,
            FormEntry.EntryStatus.IN_REVIEW,
            FormEntry.EntryStatus.READY_TO_SEND,
            FormEntry.EntryStatus.ARCHIVED,
            FormEntry.EntryStatus.DELETED,
        ]:
            with self.subTest(status=status):
                self.entry.status = status
                self.entry.save(update_fields=["status", "updated_at"])
                with self.assertRaises(ValidationError):
                    queue_entry_for_delivery(form_entry=self.entry, user=self.staff)

    def test_send_view_rejects_draft_even_for_staff_sender(self):
        FormRecipient.objects.create(form=self.form, email="draft-send@example.com")
        self.client.login(username="staff", password="pass")

        response = self.client.post(
            reverse("form_builder:entry_send_now", args=[self.entry.pk]),
            {"send_saved": "1"},
        )

        self.entry.refresh_from_db()
        self.assertRedirects(response, reverse("form_builder:entry_detail", args=[self.entry.pk]))
        self.assertEqual(self.entry.status, FormEntry.EntryStatus.DRAFT)
        self.assertFalse(OutboxItem.objects.filter(form_entry=self.entry).exists())

    def test_queue_uses_final_pdf_and_keeps_review_pdf_separate(self):
        FormRecipient.objects.create(form=self.form, email="final@example.com")
        self.entry.status = FormEntry.EntryStatus.APPROVED
        self.entry.save(update_fields=["status", "updated_at"])
        root, review_pdf = self.make_pdf(storage_key="pdf_documents/security/review.pdf")

        def fake_generate_final_pdf(*, form_entry, user, document_kind=None):
            storage_key = "pdf_documents/security/generated-final.pdf"
            pdf = PDFDocument.objects.create(
                form=form_entry.form,
                form_entry=form_entry,
                bewohner=form_entry.bewohner,
                document_kind=document_kind,
                status=PDFDocument.GenerationStatus.GENERATED,
                storage_key=storage_key,
                original_filename="generated-final.pdf",
                content_type="application/pdf",
                file_size=13,
                sha256="1" * 64,
                generated_at=timezone.now(),
                created_by=user,
                updated_by=user,
            )
            path = root / storage_key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"%PDF-1.4 test")
            return pdf

        with (
            override_settings(PRIVATE_DOCUMENT_ROOT=root),
            patch(
                "form_builder.services.generate_entry_pdf_document",
                side_effect=fake_generate_final_pdf,
            ),
        ):
            items = queue_entry_for_delivery(form_entry=self.entry, user=self.staff)

        self.assertEqual(len(items), 1)
        item = items[0]
        item.refresh_from_db()
        self.assertEqual(item.pdf_document.document_kind, PDFDocument.DocumentKind.FINAL)
        self.assertNotEqual(item.pdf_document_id, review_pdf.pk)
        self.assertEqual(
            PDFDocument.objects.filter(
                form_entry=self.entry, document_kind=PDFDocument.DocumentKind.FINAL
            ).count(),
            1,
        )

    def test_queue_reuses_existing_final_pdf_and_blocks_duplicate_pending_items(self):
        FormRecipient.objects.create(form=self.form, email="reuse@example.com")
        self.entry.status = FormEntry.EntryStatus.APPROVED
        self.entry.save(update_fields=["status", "updated_at"])
        root, final_pdf = self.make_pdf(
            storage_key="pdf_documents/security/final-existing.pdf",
            document_kind=PDFDocument.DocumentKind.FINAL,
        )

        with override_settings(PRIVATE_DOCUMENT_ROOT=root):
            items = queue_entry_for_delivery(form_entry=self.entry, user=self.staff)

        self.assertEqual(items[0].pdf_document_id, final_pdf.pk)
        self.assertEqual(
            PDFDocument.objects.filter(
                form_entry=self.entry, document_kind=PDFDocument.DocumentKind.FINAL
            ).count(),
            1,
        )

        self.entry.status = FormEntry.EntryStatus.APPROVED
        self.entry.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            queue_entry_for_delivery(form_entry=self.entry, user=self.staff)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_process_outbox_sends_and_archives(self):
        root, pdf = self.make_pdf(storage_key="pdf_documents/security/outbox.pdf")
        recipient = FormRecipient.objects.create(form=self.form, email="send@example.com")
        item = OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient,
            pdf_document=pdf,
            subject="Send",
        )
        with override_settings(PRIVATE_DOCUMENT_ROOT=root):
            result = process_outbox_queue(limit=1)
        item.refresh_from_db()
        self.entry.refresh_from_db()
        self.assertEqual(result.sent, 1)
        self.assertEqual(item.status, OutboxItem.DeliveryStatus.SENT)
        self.assertEqual(self.entry.status, FormEntry.EntryStatus.ARCHIVED)
        self.assertTrue(SentFormArchive.objects.filter(outbox_item=item).exists())

    def test_partial_recipient_success_does_not_archive_entry(self):
        self.entry.status = FormEntry.EntryStatus.READY_TO_SEND
        self.entry.save(update_fields=["status", "updated_at"])
        root, pdf = self.make_pdf(
            storage_key="pdf_documents/security/partial.pdf",
            document_kind=PDFDocument.DocumentKind.FINAL,
        )
        recipient_one = FormRecipient.objects.create(form=self.form, email="one@example.com")
        recipient_two = FormRecipient.objects.create(form=self.form, email="two@example.com")
        item_one = OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient_one,
            pdf_document=pdf,
            subject="One",
        )
        item_two = OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient_two,
            pdf_document=pdf,
            subject="Two",
            max_attempts=1,
        )

        with override_settings(PRIVATE_DOCUMENT_ROOT=root):
            mark_outbox_sent(item_one)
            mark_outbox_failed(item_two, error=RuntimeError("smtp failed"))

        self.entry.refresh_from_db()
        item_one.refresh_from_db()
        item_two.refresh_from_db()
        self.assertEqual(item_one.status, OutboxItem.DeliveryStatus.SENT)
        self.assertEqual(item_two.status, OutboxItem.DeliveryStatus.FAILED)
        self.assertEqual(self.entry.status, FormEntry.EntryStatus.READY_TO_SEND)
        self.assertIsNone(self.entry.archived_at)

    def test_entry_archives_only_after_all_recipients_are_sent(self):
        self.entry.status = FormEntry.EntryStatus.READY_TO_SEND
        self.entry.save(update_fields=["status", "updated_at"])
        root, pdf = self.make_pdf(
            storage_key="pdf_documents/security/all-sent.pdf",
            document_kind=PDFDocument.DocumentKind.FINAL,
        )
        recipient_one = FormRecipient.objects.create(form=self.form, email="sent-one@example.com")
        recipient_two = FormRecipient.objects.create(form=self.form, email="sent-two@example.com")
        item_one = OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient_one,
            pdf_document=pdf,
            subject="One",
        )
        item_two = OutboxItem.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            recipient=recipient_two,
            pdf_document=pdf,
            subject="Two",
        )

        with override_settings(PRIVATE_DOCUMENT_ROOT=root):
            mark_outbox_sent(item_one)
            self.entry.refresh_from_db()
            self.assertEqual(self.entry.status, FormEntry.EntryStatus.READY_TO_SEND)
            mark_outbox_sent(item_two)

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, FormEntry.EntryStatus.ARCHIVED)
        self.assertIsNotNone(self.entry.archived_at)

    def test_purge_expired_archives_dry_run_does_not_delete(self):
        root, pdf = self.make_pdf(storage_key="pdf_documents/security/expired-dry.pdf")
        archive = SentFormArchive.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            pdf_document=pdf,
            sent_at=timezone.now(),
            retention_until=timezone.now() - timedelta(days=1),
        )
        out = io.StringIO()
        with override_settings(PRIVATE_DOCUMENT_ROOT=root):
            call_command("purge_expired_archives", stdout=out)
        self.assertTrue(SentFormArchive.objects.filter(pk=archive.pk).exists())
        self.assertIn("Dry-run", out.getvalue())

    def test_purge_expired_archives_confirm_deletes_archive_pdf_and_file(self):
        root, pdf = self.make_pdf(storage_key="pdf_documents/security/expired.pdf")
        path = get_pdf_private_path(pdf)
        archive = SentFormArchive.objects.create(
            form=self.form,
            form_entry=self.entry,
            bewohner=self.bewohner,
            pdf_document=pdf,
            sent_at=timezone.now(),
            retention_until=timezone.now() - timedelta(days=1),
        )
        with override_settings(PRIVATE_DOCUMENT_ROOT=root):
            call_command("purge_expired_archives", "--confirm", "--delete-files")
        self.assertFalse(SentFormArchive.objects.filter(pk=archive.pk).exists())
        self.assertFalse(PDFDocument.objects.filter(pk=pdf.pk).exists())
        self.assertFalse(path.exists())


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ScheduleComputationTests(SecurityFixtureMixin, TestCase):
    def test_compute_next_run_daily_moves_to_tomorrow_after_time_passed(self):
        schedule = FormSchedule.objects.create(
            form=self.form,
            name="daily",
            trigger_type=FormSchedule.TriggerType.SCHEDULED,
            config={"frequency": "daily", "run_time": "08:00"},
        )
        base = timezone.datetime(2026, 5, 4, 9, 0, tzinfo=timezone.get_current_timezone())
        next_run = compute_next_run_at(schedule, from_time=base)
        self.assertEqual(next_run.date().isoformat(), "2026-05-05")

    def test_compute_next_run_weekly_uses_configured_weekday(self):
        schedule = FormSchedule.objects.create(
            form=self.form,
            name="weekly",
            trigger_type=FormSchedule.TriggerType.SCHEDULED,
            config={"frequency": "weekly", "weekday": 2, "run_time": "08:00"},
        )
        base = timezone.datetime(2026, 5, 4, 7, 0, tzinfo=timezone.get_current_timezone())
        next_run = compute_next_run_at(schedule, from_time=base)
        self.assertEqual(next_run.weekday(), 2)

    def test_compute_next_run_manual_returns_none(self):
        schedule = FormSchedule.objects.create(
            form=self.form, name="manual", config={"frequency": "manual"}
        )
        self.assertIsNone(compute_next_run_at(schedule))
