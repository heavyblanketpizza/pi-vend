from django.apps import AppConfig


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pivend.research"

    def ready(self):
        # Loading Kiwi's model takes a few seconds; do it in the background at
        # startup instead of during the first competitor analysis.
        import threading

        from .text import _kiwi

        threading.Thread(target=_kiwi, name="kiwi-warmup", daemon=True).start()
