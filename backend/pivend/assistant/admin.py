from django.contrib import admin

from .models import Conversation


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "updated_at")
    search_fields = ("title",)
