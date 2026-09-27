from django.contrib import admin

from .models import Credential


@admin.register(Credential)
class CredentialAdmin(admin.ModelAdmin):
    list_display = ("owner", "kind", "hint", "status", "checked_at", "updated_at")
    list_filter = ("kind", "status")
    search_fields = ("owner__username", "owner__email")
    # Secrets are never shown or editable here.
    fields = ("owner", "kind", "config", "hint", "status", "status_message", "checked_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False
