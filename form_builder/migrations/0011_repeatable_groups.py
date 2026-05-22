# Generated manually for Prompt 3 repeatable dynamic tables.

import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("form_builder", "0010_form_entry_attachments"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RepeatableGroup",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("key", models.SlugField(max_length=80)),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                (
                    "position",
                    models.PositiveIntegerField(
                        default=1, validators=[django.core.validators.MinValueValidator(1)]
                    ),
                ),
                (
                    "min_rows",
                    models.PositiveIntegerField(
                        default=0,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                    ),
                ),
                (
                    "max_rows",
                    models.PositiveIntegerField(
                        default=25,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(200),
                        ],
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("ui_config", models.JSONField(blank=True, default=dict)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_builder_repeatablegroup_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_builder_repeatablegroup_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "form",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="repeatable_groups",
                        to="form_builder.form",
                    ),
                ),
                (
                    "section",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="repeatable_groups",
                        to="form_builder.formsection",
                    ),
                ),
            ],
            options={
                "verbose_name": "Wiederholbare Tabelle",
                "verbose_name_plural": "Wiederholbare Tabellen",
                "ordering": ["form", "position", "title"],
            },
        ),
        migrations.CreateModel(
            name="RepeatableGroupColumn",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("key", models.SlugField(max_length=80)),
                ("label", models.CharField(max_length=255)),
                ("help_text", models.TextField(blank=True)),
                (
                    "column_type",
                    models.CharField(
                        choices=[
                            ("text", "Text"),
                            ("textarea", "Mehrzeilig"),
                            ("integer", "Ganzzahl"),
                            ("decimal", "Dezimalzahl"),
                            ("date", "Datum"),
                            ("boolean", "Checkbox"),
                            ("select", "Auswahl"),
                            ("file", "Datei/Foto"),
                        ],
                        default="text",
                        max_length=24,
                    ),
                ),
                (
                    "position",
                    models.PositiveIntegerField(
                        default=1, validators=[django.core.validators.MinValueValidator(1)]
                    ),
                ),
                ("required", models.BooleanField(default=False)),
                ("placeholder", models.CharField(blank=True, max_length=255)),
                ("choices", models.JSONField(blank=True, default=list)),
                ("validation_rules", models.JSONField(blank=True, default=dict)),
                ("ui_config", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_builder_repeatablegroupcolumn_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_builder_repeatablegroupcolumn_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="columns",
                        to="form_builder.repeatablegroup",
                    ),
                ),
            ],
            options={
                "verbose_name": "Tabellenspalte",
                "verbose_name_plural": "Tabellenspalten",
                "ordering": ["group", "position", "key"],
            },
        ),
        migrations.AddConstraint(
            "RepeatableGroup",
            models.UniqueConstraint(
                fields=("form", "key"), name="uniq_repeatable_group_key_per_form"
            ),
        ),
        migrations.AddConstraint(
            "RepeatableGroup",
            models.CheckConstraint(
                condition=models.Q(("max_rows__gte", models.F("min_rows"))),
                name="repeatable_group_max_gte_min",
            ),
        ),
        migrations.AddIndex(
            "RepeatableGroup",
            models.Index(fields=["form", "is_active"], name="form_builde_form_id_b6da7f_idx"),
        ),
        migrations.AddIndex(
            "RepeatableGroup",
            models.Index(fields=["section", "is_active"], name="form_builde_section_6757ef_idx"),
        ),
        migrations.AddConstraint(
            "RepeatableGroupColumn",
            models.UniqueConstraint(
                fields=("group", "key"), name="uniq_repeatable_column_key_per_group"
            ),
        ),
        migrations.AddConstraint(
            "RepeatableGroupColumn",
            models.UniqueConstraint(
                fields=("group", "position"), name="uniq_repeatable_column_position_per_group"
            ),
        ),
        migrations.AddIndex(
            "RepeatableGroupColumn",
            models.Index(fields=["group", "is_active"], name="form_builde_group_i_d6ce33_idx"),
        ),
        migrations.AddIndex(
            "RepeatableGroupColumn",
            models.Index(fields=["column_type"], name="form_builde_column__5892e4_idx"),
        ),
    ]
