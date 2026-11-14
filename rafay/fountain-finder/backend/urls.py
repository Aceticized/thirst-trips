"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from locations.forms import LoginForm
from locations.views import account, facility_check_in, signup
from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import path, include, reverse_lazy

urlpatterns = [
    # Login and sign-up as reached from an NFC check-in (they send you back to the check-in page).
    path("accounts/signup/", signup, name="signup"),
    path(
        "accounts/login/",
        LoginView.as_view(authentication_form=LoginForm, extra_context={"signup_url": reverse_lazy("signup")}),
        name="login",
    ),
    # The same login and sign-up, reached directly (https://data.thirsttrips-ua.ca/login/).
    path(
        "login/",
        LoginView.as_view(
            authentication_form=LoginForm,
            redirect_authenticated_user=True,
            next_page="account",
            extra_context={"signup_url": reverse_lazy("signup-page")},
        ),
        name="login-page",
    ),
    path("signup/", signup, {"default_destination": "account", "login_url_name": "login-page"}, name="signup-page"),
    path("account/", account, name="account"),
    path("checkin/<uuid:token>/", facility_check_in, name="check-in"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("api/", include("locations.urls")),
]