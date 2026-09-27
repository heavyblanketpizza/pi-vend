from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pivend.accounts"
    verbose_name = "계정"

    def ready(self):
        from . import checks  # noqa: F401
