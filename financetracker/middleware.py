from .services.theme_preference import cookie_kwargs, for_request


class ThemeCookieMiddleware:
    """Keep the FOUC theme cookie aligned with the authenticated profile."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            response.set_cookie(**cookie_kwargs(for_request(request)))
        return response
