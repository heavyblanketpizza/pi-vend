from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    path("signup/sent/", views.signup_sent, name="signup_sent"),
    path("signup/resend/", views.resend_verification, name="resend_verification"),
    path("verify/<uidb64>/<token>/", views.verify_email, name="verify_email"),
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path(
        "password/reset/sent/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("settings/", views.connections, name="connections"),
    path("settings/connections/<slug:slug>/save/", views.save_connection, name="save_connection"),
    path("settings/connections/<slug:slug>/test/", views.test_connection, name="test_connection"),
    path("settings/connections/<slug:slug>/delete/", views.delete_connection, name="delete_connection"),
    path("settings/account/", views.account, name="account"),
]
