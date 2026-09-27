from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dashboard/demo/", views.demo_data, name="demo_data"),
    path("data/", views.data_sources, name="data_sources"),
    path("data/stores/<int:store_id>/delete/", views.delete_store, name="delete_store"),
    path("login/", auth_views.LoginView.as_view(template_name="web/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("research/", views.keyword_research, name="research"),
    path("drafts/", views.drafts, name="drafts"),
    path("drafts/<int:draft_id>/", views.draft_detail, name="draft_detail"),
    path("drafts/<int:draft_id>/render/", views.draft_render, name="draft_render"),
    path("drafts/<int:draft_id>/approve/", views.draft_approve, name="draft_approve"),
    path("drafts/<int:draft_id>/download/", views.draft_download, name="draft_download"),
]
