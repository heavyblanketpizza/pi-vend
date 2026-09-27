from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("internal/", include("pivend.assistant.internal_urls")),
    path("chat/", include("pivend.assistant.urls")),
    path("", include("pivend.accounts.urls")),
    path("", include("pivend.web.urls")),
]

if settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(rf"^{settings.MEDIA_URL.strip('/')}/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
