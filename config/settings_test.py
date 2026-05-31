"""Test settings: in-memory SQLite, fast hashers, no external DB."""

from config.settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
