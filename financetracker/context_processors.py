from .services.money_format import locale_from_accept_language
from .services.theme_preference import for_request


def theme_preference(request):
    return {"theme_preference": for_request(request)}


def display_locale(request):
    return {
        "display_locale": locale_from_accept_language(
            request.META.get("HTTP_ACCEPT_LANGUAGE")
        )
    }
