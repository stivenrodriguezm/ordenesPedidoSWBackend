from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("api/login/", TokenObtainPairView.as_view(), name="login"),  # Alias para token
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/", include("ordenes.urls")),  # Incluye las rutas de la app ordenes
    path("admin/", admin.site.urls),
]
