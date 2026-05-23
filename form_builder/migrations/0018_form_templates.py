# Generated for reusable professional form template library.
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("form_builder", "0017_qr_contexts"),
    ]

    operations = [
        migrations.CreateModel(
            name="FormTemplate",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("key", models.SlugField(max_length=120)),
                ("version", models.PositiveIntegerField(default=1)),
                ("title", models.CharField(max_length=255)),
                ("category", models.CharField(blank=True, db_index=True, max_length=120)),
                ("description", models.TextField(blank=True)),
                ("language", models.CharField(default="de", max_length=16)),
                ("tags", models.JSONField(blank=True, default=list)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Entwurf"),
                            ("active", "Aktiv"),
                            ("retired", "Ausgemustert"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=16,
                    ),
                ),
                (
                    "definition",
                    models.JSONField(
                        default=dict,
                        help_text="Portable template payload with form metadata, sections, fields, repeatable groups, conditional rules and action-item rules.",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_builder_formtemplate_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_builder_formtemplate_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Formularvorlage",
                "verbose_name_plural": "Formularvorlagen",
                "ordering": ["category", "title", "-version"],
            },
        ),
        migrations.AddConstraint(
            model_name="formtemplate",
            constraint=models.UniqueConstraint(
                fields=("key", "version"), name="uniq_form_template_key_version"
            ),
        ),
        migrations.AddIndex(
            model_name="formtemplate",
            index=models.Index(fields=["status", "category"], name="form_builde_status_1b305f_idx"),
        ),
        migrations.AddIndex(
            model_name="formtemplate",
            index=models.Index(fields=["key", "status"], name="form_builde_key_beb9e5_idx"),
        ),
    ]
