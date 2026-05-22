# Generated for Excel import foundation.

import uuid

import django.db.models.deletion
import form_builder.excel_import_models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("form_builder", "0012_conditional_rules"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportJob",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "uploaded_file",
                    models.FileField(
                        max_length=500,
                        upload_to=form_builder.excel_import_models.excel_import_upload_to,
                    ),
                ),
                ("original_filename", models.CharField(max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("uploaded", "Hochgeladen"),
                            ("analyzed", "Analysiert"),
                            ("mapped", "Mapping gespeichert"),
                            ("generated", "Entwuerfe erzeugt"),
                            ("failed", "Fehlgeschlagen"),
                        ],
                        db_index=True,
                        default="uploaded",
                        max_length=24,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("analysis_result", models.JSONField(blank=True, default=dict)),
                ("mapping", models.JSONField(blank=True, default=dict)),
                ("generated_form_ids", models.JSONField(blank=True, default=list)),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="excel_import_jobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Excel-Import",
                "verbose_name_plural": "Excel-Importe",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ImportedSheet",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sheet_index", models.PositiveIntegerField()),
                ("name", models.CharField(max_length=255)),
                ("used_range", models.CharField(blank=True, max_length=64)),
                ("row_count", models.PositiveIntegerField(default=0)),
                ("column_count", models.PositiveIntegerField(default=0)),
                ("analysis", models.JSONField(blank=True, default=dict)),
                ("selected", models.BooleanField(default=True)),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sheets",
                        to="form_builder.importjob",
                    ),
                ),
            ],
            options={
                "verbose_name": "Importiertes Excel-Blatt",
                "verbose_name_plural": "Importierte Excel-Blaetter",
                "ordering": ["job", "sheet_index"],
            },
        ),
        migrations.CreateModel(
            name="FieldMapping",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_ref", models.CharField(blank=True, max_length=120)),
                (
                    "target_kind",
                    models.CharField(
                        choices=[
                            ("field", "Feld"),
                            ("section", "Abschnitt"),
                            ("table", "Tabelle"),
                            ("column", "Tabellenspalte"),
                        ],
                        default="field",
                        max_length=24,
                    ),
                ),
                ("target_key", models.SlugField(max_length=80)),
                ("label", models.CharField(max_length=255)),
                (
                    "field_type",
                    models.CharField(
                        choices=[
                            ("text", "Text"),
                            ("textarea", "Mehrzeilig"),
                            ("checkbox", "Checkbox"),
                            ("date", "Datum"),
                            ("number", "Zahl"),
                            ("select", "Auswahl"),
                            ("table", "Tabelle"),
                            ("file", "Datei/Foto"),
                        ],
                        default="text",
                        max_length=24,
                    ),
                ),
                ("required", models.BooleanField(default=False)),
                ("config", models.JSONField(blank=True, default=dict)),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="field_mappings",
                        to="form_builder.importjob",
                    ),
                ),
                (
                    "sheet",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="field_mappings",
                        to="form_builder.importedsheet",
                    ),
                ),
            ],
            options={
                "verbose_name": "Excel-Feldmapping",
                "verbose_name_plural": "Excel-Feldmappings",
                "ordering": ["job", "sheet__sheet_index", "target_kind", "created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="importjob",
            index=models.Index(fields=["status", "created_at"], name="form_builde_status_1ed79c_idx"),
        ),
        migrations.AddIndex(
            model_name="importjob",
            index=models.Index(fields=["uploaded_by", "created_at"], name="form_builde_uploade_62d2e8_idx"),
        ),
        migrations.AddIndex(
            model_name="importedsheet",
            index=models.Index(fields=["job", "selected"], name="form_builde_job_id_87030e_idx"),
        ),
        migrations.AddConstraint(
            model_name="importedsheet",
            constraint=models.UniqueConstraint(fields=("job", "sheet_index"), name="uniq_imported_sheet_index"),
        ),
        migrations.AddConstraint(
            model_name="importedsheet",
            constraint=models.UniqueConstraint(fields=("job", "name"), name="uniq_imported_sheet_name"),
        ),
        migrations.AddIndex(
            model_name="fieldmapping",
            index=models.Index(fields=["job", "target_kind"], name="form_builde_job_id_650dbe_idx"),
        ),
        migrations.AddIndex(
            model_name="fieldmapping",
            index=models.Index(fields=["sheet", "target_kind"], name="form_builde_sheet_i_834ee5_idx"),
        ),
    ]
