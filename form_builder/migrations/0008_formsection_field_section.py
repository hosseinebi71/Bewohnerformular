# Generated manually for FormSection support.

import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("form_builder", "0007_org_unit_scopes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FormSection",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                (
                    "description",
                    models.TextField(
                        blank=True,
                        help_text="Beschreibung oder Hilfetext fuer diesen Formularabschnitt.",
                    ),
                ),
                (
                    "position",
                    models.PositiveIntegerField(
                        help_text="Technische Reihenfolge innerhalb des Formulars.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "is_collapsible",
                    models.BooleanField(
                        default=False,
                        help_text="Wenn aktiv, kann der Abschnitt in der Oberflaeche einklappbar dargestellt werden.",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "form",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sections",
                        to="form_builder.form",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Formularabschnitt",
                "verbose_name_plural": "Formularabschnitte",
                "ordering": ["form", "position", "title"],
            },
        ),
        migrations.AddField(
            model_name="field",
            name="section",
            field=models.ForeignKey(
                blank=True,
                help_text="Optionaler Formularabschnitt. Leer bedeutet: globales Feld ohne Abschnitt.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="fields",
                to="form_builder.formsection",
            ),
        ),
        migrations.AddConstraint(
            model_name="formsection",
            constraint=models.UniqueConstraint(
                fields=("form", "position"), name="uniq_form_section_position_per_form"
            ),
        ),
        migrations.AddIndex(
            model_name="formsection",
            index=models.Index(fields=["form", "is_active"], name="form_builde_form_id_9f5d8d_idx"),
        ),
        migrations.AddIndex(
            model_name="field",
            index=models.Index(fields=["section", "is_active"], name="form_builde_section_7406d6_idx"),
        ),
    ]
