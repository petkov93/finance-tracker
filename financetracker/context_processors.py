from .models import DEFAULT_PROFILE_THEME, ensure_user_profile


def theme_preference(request):
    if getattr(request, "user", None) is not None and request.user.is_authenticated:
        profile = ensure_user_profile(request.user)
        return {"theme_preference": profile.theme}
    return {"theme_preference": DEFAULT_PROFILE_THEME}
