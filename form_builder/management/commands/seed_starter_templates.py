from __future__ import annotations

from django.core.management.base import BaseCommand

from form_builder.form_template_models import FormTemplate
from form_builder.starter_template_data import STARTER_TEMPLATES


class Command(BaseCommand):
    help = "Seed professional German starter form templates idempotently."

    def add_arguments(self, parser):
        parser.add_argument(
            "--retire-missing",
            action="store_true",
            help="Retire active templates not present in the seed list.",
        )

    def handle(self, *args, **options):
        created = 0
        updated = 0
        seen_keys = set()
        for item in STARTER_TEMPLATES:
            seen_keys.add((item["key"], item.get("version", 1)))
            defaults = {
                "title": item["title"],
                "category": item.get("category", ""),
                "description": item.get("description", ""),
                "language": item.get("language", "de"),
                "tags": item.get("tags", []),
                "status": FormTemplate.TemplateStatus.ACTIVE,
                "definition": item["definition"],
            }
            _, was_created = FormTemplate.objects.update_or_create(
                key=item["key"], version=item.get("version", 1), defaults=defaults
            )
            if was_created:
                created += 1
            else:
                updated += 1
        retired = 0
        if options["retire_missing"]:
            for template in FormTemplate.objects.filter(status=FormTemplate.TemplateStatus.ACTIVE):
                if (template.key, template.version) not in seen_keys:
                    template.status = FormTemplate.TemplateStatus.RETIRED
                    template.save(update_fields=["status", "updated_at"])
                    retired += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Startervorlagen synchronisiert: {created} neu, {updated} aktualisiert, {retired} ausgemustert."
            )
        )
