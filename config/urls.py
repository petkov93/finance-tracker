from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import TemplateView

from financetracker.sitemaps import StaticViewSitemap

sitemaps = {
    "static": StaticViewSitemap,
}


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("", include("financetracker.urls")),
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain")),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
]
