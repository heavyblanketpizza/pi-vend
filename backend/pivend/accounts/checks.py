from cryptography.fernet import Fernet
from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def credential_keys(app_configs, **kwargs):
    keys = settings.CREDENTIAL_ENCRYPTION_KEYS
    if not keys:
        return [Error("CREDENTIAL_ENCRYPTION_KEYS is not set; users can't save API keys.", id="pivend.E001")]
    try:
        for key in keys:
            Fernet(key)
    except ValueError:
        return [Error("CREDENTIAL_ENCRYPTION_KEYS contains an invalid Fernet key.", id="pivend.E002")]
    return []
