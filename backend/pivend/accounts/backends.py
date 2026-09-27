from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailBackend(ModelBackend):
    """Log in with an email address (case-insensitive) or, for accounts
    created by an admin, a username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or password is None:
            return None
        User = get_user_model()
        identifier = username.strip()
        user = (
            User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier))
            .order_by("id")
            .first()
        )
        if user is None:
            User().set_password(password)  # same cost as a real check (timing)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
