from .services.theme_preference import for_request


def theme_preference(request):
    return {"theme_preference": for_request(request)}
