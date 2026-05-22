# Generated for Bewohnerformular conditional dynamic-form rules.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("form_builder", "0011_repeatable_groups"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConditionalRule",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "operator",
                    models.CharField(
                        choices=[
                            ("equals", "ist gleich"),
                            ("not_equals", "ist nicht gleich"),
                            ("is_empty", "ist leer"),
                            ("is_not_empty", "ist nicht leer"),
                        ],
                        default="equals",
                        max_length=24,
                    ),
                ),
                (
                    "value",
                    models.CharField(
                        blank=True,
                        help_text="Vergleichswert fuer equals/not_equals. Bei Leer-Operatoren frei lassen.",
                        max_length=255,
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("show", "anzeigen"),
                            ("hide", "ausblenden"),
                            ("require", "verpflichtend machen"),
                        ],
                        default="show",
                        max_length=16,
                    ),
                ),
                (
                    "message",
                    models.CharField(
                        blank=True,
                        help_text="Optionale Fehlermeldung fuer require-Regeln.",
                        max_length=255,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_builder_conditionalrule_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "form",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conditional_rules",
                        to="form_builder.form",
                    ),
                ),
                (
                    "source_field",
                    models.ForeignKey(
                        help_text="Feld, dessen Wert die Regel ausloest.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conditional_rules_as_source",
                        to="form_builder.field",
                    ),
                ),
                (
                    "target_field",
                    models.ForeignKey(
                        blank=True,
                        help_text="Zielfeld fuer show/hide/require.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conditional_rules_as_target",
                        to="form_builder.field",
                    ),
                ),
                (
                    "target_section",
                    models.ForeignKey(
                        blank=True,
                        help_text="Optionaler Zielabschnitt. Genau ein Ziel muss gesetzt sein.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conditional_rules_as_target",
                        to="form_builder.formsection",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="form_builder_conditionalrule_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Bedingte Formularregel",
                "verbose_name_plural": "Bedingte Formularregeln",
                "ordering": ["form", "source_field__position", "action", "created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="conditionalrule",
            index=models.Index(fields=["form", "is_active"], name="form_builde_form_id_6a8b4d_idx"),
        ),
        migrations.AddIndex(
            model_name="conditionalrule",
            index=models.Index(
                fields=["source_field", "operator"], name="form_builde_source__598e0d_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="conditionalrule",
            index=models.Index(
                fields=["target_field", "action"], name="form_builde_target__cc4c84_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="conditionalrule",
            index=models.Index(
                fields=["target_section", "action"], name="form_builde_target__076d70_idx"
            ),
        ),
    ]
