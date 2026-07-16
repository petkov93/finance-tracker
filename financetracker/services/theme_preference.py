from django.contrib.auth.models import User

from financetracker.models import ensure_user_profile

from .theme_constants import DEFAULT_THEME_PREFERENCE, THEME_COOKIE_NAME, THEME_VALUES

_REQUEST_CACHE_ATTR = "_financetracker_theme_preference"


def preference_for(user: User | None) -> str:
    if user is None or not user.is_authenticated:
        return DEFAULT_THEME_PREFERENCE
    profile = ensure_user_profile(user)
    return profile.theme


def set_preference(user: User, value: str) -> str:
    if value not in THEME_VALUES:
        raise ValueError(f"Invalid theme preference: {value!r}")
    profile = ensure_user_profile(user)
    profile.theme = value
    profile.save(update_fields=["theme"])
    return value


def cookie_kwargs(preference: str) -> dict:
    return {
        "key": THEME_COOKIE_NAME,
        "value": preference,
        "max_age": 60 * 60 * 24 * 365,
        "samesite": "Lax",
        "httponly": False,
    }


def for_request(request) -> str:
    cached = getattr(request, _REQUEST_CACHE_ATTR, None)
    if cached is not None:
        return cached
    user = getattr(request, "user", None)
    preference = preference_for(user)
    setattr(request, _REQUEST_CACHE_ATTR, preference)
    return preference
