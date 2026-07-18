from django.utils import timezone

from .services.iou import upcoming_iou_alerts
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


def iou_alerts(request):
    if not request.user.is_authenticated:
        return {}
    today = timezone.now().date()
    alerts = upcoming_iou_alerts(request.user, today=today)
    return {
        "iou_alerts": alerts,
        "iou_alert_count": len(alerts),
        "today": today,
    }
