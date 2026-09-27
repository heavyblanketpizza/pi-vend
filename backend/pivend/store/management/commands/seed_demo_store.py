"""Generate a realistic demo store so the dashboard can be explored before real data is connected.

    python manage.py seed_demo_store --user <username> [--days 120]
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from pivend.store.demo import create_demo


class Command(BaseCommand):
    help = "Create demo stores with realistic sales, traffic, keyword and ad data."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True)
        parser.add_argument("--days", type=int, default=120)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, user, days, seed, **options):
        owner = get_user_model().objects.filter(username=user).first()
        if owner is None:
            raise CommandError(f"User {user!r} not found")
        result = create_demo(owner, days=days, seed=seed)
        self.stdout.write(self.style.SUCCESS(
            f"Demo stores for {user}: {result['sales']} sales rows, {result['keywords']} keyword rows, "
            f"{result['ads']} ad rows ({days} days to {result['end']})."
        ))
