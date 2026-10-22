import logging

from django.db.models import Q
from rest_framework.permissions import BasePermission

logger = logging.getLogger(__name__)


class IsAdministradorRole(BasePermission):
    """
    Permite acceso solo a usuarios designados explícitamente con el rol administrador.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'administrador')


# Catálogo único de equivalencias (P02-03). Clave = código que exige el backend;
# valor = códigos guardados en RolePermission que lo satisfacen. Incluye los
# códigos que ofrece la pantalla de permisos (UsuariosPage) y los heredados, para
# que configurar un permiso en la UI tenga efecto real en la API.
PERMISSION_ALIASES = {
    'VER_RECIBOS': {'VER_RECIBOS', 'ACCESO_RECIBOS'},
    'ACCESO_RECIBOS': {'VER_RECIBOS', 'ACCESO_RECIBOS'},
    'VER_CAJA': {'VER_CAJA', 'ACCESO_CAJA'},
    'ACCESO_CAJA': {'VER_CAJA', 'ACCESO_CAJA'},
    'VER_COMPROBANTES_EGRESO': {'VER_COMPROBANTES_EGRESO', 'ACCESO_EGRESOS', 'VER_TODOS_EGRESOS', 'VER_PROPIOS_EGRESOS'},
    'ACCESO_EGRESOS': {'VER_COMPROBANTES_EGRESO', 'ACCESO_EGRESOS', 'VER_TODOS_EGRESOS', 'VER_PROPIOS_EGRESOS'},
    'CREAR_ITEM_INVENTARIO': {'CREAR_ITEM_INVENTARIO', 'CREAR_ENTRADA_MANUAL', 'CREAR_GRUPO_INVENTARIO', 'CREAR_FACTURA'},
    'CREAR_ENTRADA_MANUAL': {'CREAR_ITEM_INVENTARIO', 'CREAR_ENTRADA_MANUAL', 'CREAR_GRUPO_INVENTARIO', 'CREAR_FACTURA'},
    'CREAR_GRUPO_INVENTARIO': {'CREAR_ITEM_INVENTARIO', 'CREAR_ENTRADA_MANUAL', 'CREAR_GRUPO_INVENTARIO', 'CREAR_FACTURA'},
    # La UI ofrece "ver todas" / "ver propias"; el backend pedía VER_VENTAS, que
    # la UI no permite marcar. El alcance (todas o propias) lo aplica ventas_visibles().
    'VER_VENTAS': {'VER_VENTAS', 'VER_TODAS_VENTAS', 'VER_PROPIAS_VENTAS'},
    # ADMINISTRAR_BASES es el código heredado; la UI ofrece uno por catálogo.
    'ADMINISTRAR_REFERENCIAS': {'ADMINISTRAR_BASES', 'ADMINISTRAR_REFERENCIAS'},
    'ADMINISTRAR_PROVEEDORES': {'ADMINISTRAR_BASES', 'ADMINISTRAR_PROVEEDORES'},
    'ADMINISTRAR_SEDES': {'ADMINISTRAR_BASES', 'ADMINISTRAR_SEDES'},
}

# Permisos financieros asignados por defecto al rol auxiliar cuando el rol no
# tiene fila de configuración. Es la ÚNICA fuente: la usan la API y /user/.
AUXILIAR_FINANCIAL_FEATURES = {
    'VER_RECIBOS', 'ACCESO_RECIBOS', 'VER_CAJA', 'ACCESO_CAJA', 'CERRAR_CAJA',
    'VER_COMPROBANTES_EGRESO', 'ACCESO_EGRESOS', 'VER_TODOS_EGRESOS', 'VER_PROPIOS_EGRESOS',
    'CREAR_RECIBO', 'APROBAR_RECIBO', 'CREAR_INGRESO_CAJA', 'CREAR_EGRESO_CAJA',
    'CREAR_COMPROBANTE_EGRESO', 'APROBAR_EGRESO', 'EXPORTAR_EGRESOS', 'VER_VENTAS',
    'VER_ORDENES', 'VER_CLIENTES', 'VER_INVENTARIO', 'CREAR_FACTURA',
    'EDITAR_FACTURA', 'VER_FACTURAS', 'CREAR_ITEM_INVENTARIO',
    'CREAR_ENTRADA_MANUAL', 'CREAR_GRUPO_INVENTARIO', 'EDITAR_ITEM_INVENTARIO',
    'VER_MARGENES',
}

# Contabilidad sin fila de configuración: ver ventas, recibos y comprobantes y marcar ventas
# facturadas; nunca crear ni editar (2026-10-21). La migración siembra esta misma fila.
CONTABILIDAD_FEATURES = {
    'VER_TODAS_VENTAS', 'VER_PRECIOS_VENTA', 'MARCAR_VENTA_FACTURADA',
    'ACCESO_RECIBOS', 'VER_RECIBOS', 'ACCESO_EGRESOS', 'VER_COMPROBANTES_EGRESO', 'VER_TODOS_EGRESOS',
}

ROLES = ('vendedor', 'administrador', 'auxiliar', 'transportador', 'marketing', 'contabilidad')


def permisos_efectivos(user):
    """Conjunto de códigos de permiso del usuario. 'ALL' significa acceso total
    (solo el rol administrador). Distingue rol sin configuración (usa los
    valores por defecto) de una lista deliberadamente vacía (sin permisos)."""
    if not user or not user.is_authenticated:
        return set()
    if user.role == 'administrador':
        return {'ALL'}
    from .models import RolePermission
    rp = RolePermission.objects.filter(role=user.role).first()
    if rp is not None and isinstance(rp.permissions, list):
        # 'ALL' es un valor heredado que ya no es un permiso configurable desde
        # la UI; se ignora una vez que existe una configuración explícita.
        perms = set(rp.permissions)
        perms.discard('ALL')
    elif user.role == 'auxiliar':
        perms = set(AUXILIAR_FINANCIAL_FEATURES)
    elif user.role == 'contabilidad':
        perms = set(CONTABILIDAD_FEATURES)
    else:
        perms = set()
    if user.role == 'transportador':
        # El transportador siempre puede ver sus remisiones asignadas.
        perms.add('VER_REMISIONES')
    return perms


def _permisos_de_request(request):
    cache = getattr(request, '_role_permissions_cache', None)
    if cache is None:
        cache = permisos_efectivos(request.user)
        request._role_permissions_cache = cache
    return cache


def tiene_permiso_codigo(request, feature_code):
    """True si el usuario de la petición tiene el permiso (o un equivalente)."""
    if not request or not getattr(request, 'user', None) or not request.user.is_authenticated:
        return False
    perms = _permisos_de_request(request)
    if 'ALL' in perms:
        return True
    return any(code in perms for code in PERMISSION_ALIASES.get(feature_code, {feature_code}))


def check_feature_permission(feature_code):
    """
    Generates a DRF BasePermission class dynamically to strictly check if the
    authenticated user has the specific feature permission in their RolePermission rules.
    """
    class DynamicFeaturePermission(BasePermission):
        def has_permission(self, request, view):
            return tiene_permiso_codigo(request, feature_code)

    return DynamicFeaturePermission


# ---------------------------------------------------------------------------
# Alcance por objeto (P02-01): una sola definición para consulta y escritura.
# ---------------------------------------------------------------------------

def ve_todas_las_ventas(request):
    """Rol vendedor o permiso 'solo propias' sin 'todas' → solo propias/compartidas.
    Los demás roles conservan el alcance completo que ya tenían."""
    user = request.user
    if user.role == 'administrador' or tiene_permiso_codigo(request, 'VER_TODAS_VENTAS'):
        return True
    perms = _permisos_de_request(request)
    if user.role == 'vendedor' or 'VER_PROPIAS_VENTAS' in perms:
        return False
    return True


def filtro_ventas_propias(user, prefijo=''):
    return Q(**{f'{prefijo}vendedor': user}) | Q(**{f'{prefijo}vendedores_compartidos': user})


def ventas_visibles(request, queryset=None):
    from .models import Venta
    qs = Venta.objects.all() if queryset is None else queryset
    if ve_todas_las_ventas(request):
        return qs
    return qs.filter(filtro_ventas_propias(request.user)).distinct()


def clientes_visibles(request):
    """Clientes del alcance comercial: historial, calidad y descargas masivas.

    El directorio básico conserva su consulta global para buscar por documento
    al crear una venta; esto no autoriza a consultar ventas ajenas.
    """
    from .models import Cliente
    qs = Cliente.objects.order_by('id')
    if not ve_todas_las_ventas(request):
        qs = qs.filter(pk__in=ventas_visibles(request).order_by().values('cliente_id'))
    return qs


def ordenes_visibles(request, queryset=None):
    """Alcance de órdenes para el listado y las rutas de detalle/alternativas:
    con VER_TODAS_ORDENES, todas; el rol vendedor (o quien solo tiene
    VER_PROPIAS_ORDENES) ve las suyas o las de sus ventas; los demás roles
    conservan el listado completo que ya tenían (p. ej. auxiliar al facturar)."""
    from .models import OrdenPedido
    qs = OrdenPedido.objects.all() if queryset is None else queryset
    if tiene_permiso_codigo(request, 'VER_TODAS_ORDENES'):
        return qs
    perms = _permisos_de_request(request)
    if request.user.role == 'vendedor' or 'VER_PROPIAS_ORDENES' in perms:
        u = request.user
        return qs.filter(Q(usuario=u) | Q(venta__vendedor=u) | Q(venta__vendedores_compartidos=u)).distinct()
    return qs
