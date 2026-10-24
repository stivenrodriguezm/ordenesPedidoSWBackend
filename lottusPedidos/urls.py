from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView
from rest_framework.throttling import ScopedRateThrottle
from django.conf import settings
from django.conf.urls.static import static

from .auth import RefreshUsuarioActivoView
from .health import health


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Login con límite estricto por IP para mitigar fuerza bruta."""
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'


urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/login/", ThrottledTokenObtainPairView.as_view(), name="login"),  # Alias para token
    path("api/token/", ThrottledTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", RefreshUsuarioActivoView.as_view(), name="token_refresh"),
    # Cierre de sesión: revoca el refresh token recibido (el access vence solo).
    path("api/logout/", TokenBlacklistView.as_view(), name="logout"),
    path("api/suministros/", include("suministros.urls")),
    path("api/paginaweb/", include("paginaweb.urls")),
    path("api/listaprecios/", include("listaprecios.urls")),
    path("api/pagos-bancarios/", include("pagos.urls")),
    path("api/impresion/", include("impresion.urls")),
    path("api/", include("ordenes.urls")),  # Incluye las rutas de la app ordenes
    path("admin/", admin.site.urls),
]

import os

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static('/uploads/', document_root=os.path.join(settings.MEDIA_ROOT, 'uploads'))
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
