import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from form_builder.models import Bewohner, Form


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class FrontendCssContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(
            username="frontend_user",
            password="pass",
            is_staff=True,
        )
        cls.form = Form.objects.create(
            key="frontend-form",
            version=1,
            title="Frontend Form",
            status=Form.PublicationStatus.PUBLISHED,
            published_at=timezone.now(),
            schema={"fields": []},
        )
        cls.bewohner = Bewohner.objects.create(
            resident_number="FRONT-001",
            first_name="Front",
            last_name="End",
        )
        cls.css_classes = set(
            re.findall(
                r"\.([A-Za-z_][A-Za-z0-9_-]*)",
                Path("static/form_builder/app.css").read_text(encoding="utf-8"),
            )
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _missing_classes(self, html: str) -> set[str]:
        rendered = {
            klass
            for class_attr in re.findall(r'class="([^"]+)"', html)
            for klass in class_attr.split()
            if not klass.startswith("message")
        }
        return rendered - self.css_classes

    def test_dashboard_and_entry_create_use_only_defined_css_classes(self):
        urls = [
            reverse("form_builder:dashboard"),
            reverse("form_builder:form_list"),
            reverse("form_builder:entry_create", args=[self.form.pk]),
        ]

        missing_by_url = {}
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            missing = self._missing_classes(response.content.decode("utf-8"))
            if missing:
                missing_by_url[url] = sorted(missing)

        self.assertEqual(missing_by_url, {})
