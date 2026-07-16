from .models import ensure_user_profile, theme_cookie_kwargs


class ThemeCookieMiddleware:
    """Keep the FOUC theme cookie aligned with the authenticated profile."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            profile = ensure_user_profile(user)
            response.set_cookie(**theme_cookie_kwargs(profile.theme))
        return response
