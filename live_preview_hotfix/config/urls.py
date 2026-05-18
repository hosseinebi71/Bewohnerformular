from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path(
        "accounts/profile/",
        RedirectView.as_view(pattern_name="form_builder:profile", permanent=False),
        name="accounts_profile_redirect",
    ),
    path(
        "profile/",
        RedirectView.as_view(pattern_name="form_builder:profile", permanent=False),
        name="profile_redirect",
    ),
    path("", include("form_builder.urls")),
]
