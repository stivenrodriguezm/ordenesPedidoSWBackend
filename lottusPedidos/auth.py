"""Renovación de tokens que respeta la desactivación de usuarios (P02-04/05).

simplejwt 5.3.1 renueva un refresh aunque la cuenta ya esté desactivada: así
"desactivar" no cortaba el acceso hasta que venciera el refresh."""
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView


class RefreshUsuarioActivoSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        token = RefreshToken(attrs['refresh'])
        user_id = token.payload.get(api_settings.USER_ID_CLAIM)
        if not get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: user_id}, is_active=True).exists():
            raise InvalidToken('La cuenta está desactivada.')
        return super().validate(attrs)


class RefreshUsuarioActivoView(TokenRefreshView):
    serializer_class = RefreshUsuarioActivoSerializer
