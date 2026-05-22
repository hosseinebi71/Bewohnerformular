# Generated for secure dynamic form entry attachments and auditable signatures.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import form_builder.attachment_models


class Migration(migrations.Migration):
    dependencies = [
        ("form_builder", "0009_rename_form_builde_section_7406d6_idx_form_builde_section_adedc7_idx_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FormEntryAttachment",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("field_key", models.SlugField(db_index=True, max_length=80)),
                (
                    "kind",
                    models.CharField(
                        choices=[("file", "Datei"), ("signature", "Unterschrift")],
                        default="file",
                        max_length=24,
                    ),
                ),
                ("original_filename", models.CharField(max_length=255)),
                (
                    "file",
                    models.FileField(
                        max_length=500,
                        upload_to=form_builder.attachment_models.form_entry_attachment_upload_to,
                    ),
                ),
                ("content_type", models.CharField(max_length=120)),
                ("size", models.PositiveBigIntegerField(default=0)),
                ("sha256", models.CharField(db_index=True, max_length=64)),
                ("signed_at", models.DateTimeField(blank=True, null=True)),
                ("signature_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "deleted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_entry_attachments_deleted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "entry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="form_builder.formentry",
                    ),
                ),
                (
                    "field",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="entry_attachments",
                        to="form_builder.field",
                    ),
                ),
                (
                    "signed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_entry_signatures_signed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_entry_attachments_uploaded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Formular-Anhang",
                "verbose_name_plural": "Formular-Anhaenge",
                "ordering": ["field_key", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="formentryattachment",
            index=models.Index(fields=["entry", "field_key", "deleted_at"], name="form_builde_entry_i_91c1f7_idx"),
        ),
        migrations.AddIndex(
            model_name="formentryattachment",
            index=models.Index(fields=["entry", "kind"], name="form_builde_entry_i_5edc01_idx"),
        ),
        migrations.AddIndex(
            model_name="formentryattachment",
            index=models.Index(fields=["uploaded_by", "created_at"], name="form_builde_uploade_a1cfd8_idx"),
        ),
    ]
