from django.core.management.base import BaseCommand

from pivend.accounts import crypto
from pivend.accounts.models import Credential


class Command(BaseCommand):
    help = "Re-encrypt stored credentials with the first key in CREDENTIAL_ENCRYPTION_KEYS."

    def handle(self, *args, **options):
        count = 0
        for credential in Credential.objects.exclude(secret_blob="").iterator():
            credential.secret_blob = crypto.rotate(credential.secret_blob)
            credential.save(update_fields=["secret_blob"])
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {count} credential(s). Old keys can now be removed."))
