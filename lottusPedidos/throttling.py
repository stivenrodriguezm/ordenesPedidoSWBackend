"""Límites por usuario: la actividad en vivo no consume el cupo operativo."""
import re

from rest_framework.throttling import UserRateThrottle


# Solo las consultas que se actualizan automáticamente en la oficina/chat.
# Las acciones, exportaciones y demás consultas conservan el límite diario.
_ACTUALIZACIONES = re.compile(
    r'^/api/(?:'
    r'oficina/(?:estado|coordinacion|interacciones|equipo|conversaciones|'
    r'mensajes(?:/\d+)?|trabajos(?:/\d+)?|informes/\d+)|'
    r'asistente/(?:estado|oficina-actividad|conversaciones(?:/\d+)?|'
    r'mensajes/\d+|automatizaciones(?:/\d+(?:/ejecuciones)?)?|ejecuciones/\d+|agente/trabajos(?:/\d+)?)'
    r')/\Z'
)


class ApiUserRateThrottle(UserRateThrottle):
    def allow_request(self, request, view):
        self.scope = 'user'
        if request.user and request.user.is_authenticated:
            # Nueva clave: el contador anterior mezcla sondeos con operaciones
            # y puede estar agotado antes de actualizar esta política.
            self.scope = 'api_user'
            if request.method in ('GET', 'HEAD'):
                if request.path_info == '/api/user/':
                    self.scope = 'session'
                elif _ACTUALIZACIONES.fullmatch(request.path_info):
                    self.scope = 'office_live'
            elif request.method == 'POST' and request.path_info == '/api/oficina/presencia/':
                self.scope = 'office_presence'
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_rate(self):
        # La cuota operativa sigue usando la configuración existente 'user'.
        scope = 'user' if self.scope == 'api_user' else self.scope
        return self.THROTTLE_RATES[scope]
