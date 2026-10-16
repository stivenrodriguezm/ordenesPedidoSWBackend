"""Esquema compacto de la base de datos para el asistente, generado de los modelos de
Django (siempre al día). Sirve para que la IA entienda cómo habla el usuario de los
datos; las consultas siguen pasando solo por las herramientas de solo lectura."""
from functools import lru_cache

from django.apps import apps

APPS = ['ordenes', 'suministros', 'paginaweb', 'listaprecios']
# Internos o sin valor para el negocio.
EXCLUIDOS = {'ConversacionAsistente', 'MensajeAsistente', 'PerfilAsistente', 'DocumentoPerfilAsistente',
             'AprendizajeAsistente', 'RespuestaIdempotente', 'RegistroAuditoria'}
OCULTOS = {'password', 'last_login', 'is_superuser', 'is_staff', 'groups', 'user_permissions', 'token', 'clave'}


def _campo(f):
    if f.is_relation and f.related_model:
        return f'{f.name}→{f.related_model.__name__}'
    if getattr(f, 'choices', None):
        return f"{f.name}[{'/'.join(str(c[0]) for c in f.choices)[:90]}]"
    return f.name


def _descripcion(m):
    doc = ' '.join((m.__doc__ or '').split())
    # Django genera «Modelo(id, campo, …)» cuando no hay docstring: no aporta.
    if not doc or doc.startswith(f'{m.__name__}('):
        return ''
    return f' — {doc[:160]}'


@lru_cache(maxsize=1)
def texto():
    lineas = ['## Base de datos (modelos y campos)',
              'Modelo: campos (→ relación, [valores posibles]). Úsalo para entender el lenguaje del usuario; '
              'los datos se consultan solo con las herramientas.']
    for app in APPS:
        try:
            config = apps.get_app_config(app)
        except LookupError:
            continue
        lineas.append(f'### {app}')
        for m in config.get_models():
            if m.__name__ in EXCLUIDOS:
                continue
            campos = [_campo(f) for f in m._meta.get_fields()
                      if (f.concrete or f.many_to_many) and not (f.auto_created and not f.concrete) and f.name not in OCULTOS]
            lineas.append(f'- {m.__name__}{_descripcion(m)}: {", ".join(campos)}')
    return '\n'.join(lineas)
