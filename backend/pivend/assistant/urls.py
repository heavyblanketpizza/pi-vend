from django.urls import path

from . import views

urlpatterns = [
    path("", views.chat, name="chat"),
    path("new/", views.new_conversation, name="chat_new"),
    path("<int:conversation_id>/", views.chat, name="chat_conversation"),
    path("<int:conversation_id>/send/", views.send_message, name="chat_send"),
    path("health/", views.health, name="agent_health"),
]
