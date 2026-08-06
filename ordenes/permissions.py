from rest_framework.permissions import BasePermission

class IsAdministradorRole(BasePermission):
    """
    Permite acceso solo a usuarios designados explícitamente con el rol administrador.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'administrador')

# Mapeo de sinónimos de permisos (Frontend vs Backend)
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
}

# Permisos financieros asignados por defecto al rol auxiliar
AUXILIAR_FINANCIAL_FEATURES = {
    'VER_RECIBOS', 'ACCESO_RECIBOS', 'VER_CAJA', 'ACCESO_CAJA',
    'VER_COMPROBANTES_EGRESO', 'ACCESO_EGRESOS', 'VER_TODOS_EGRESOS', 'VER_PROPIOS_EGRESOS',
    'CREAR_RECIBO', 'APROBAR_RECIBO', 'CREAR_INGRESO_CAJA', 'CREAR_EGRESO_CAJA',
    'CREAR_COMPROBANTE_EGRESO', 'APROBAR_EGRESO', 'EXPORTAR_EGRESOS', 'VER_VENTAS',
    'VER_ORDENES', 'VER_CLIENTES', 'VER_INVENTARIO', 'CREAR_FACTURA',
    'EDITAR_FACTURA', 'VER_FACTURAS', 'CREAR_ITEM_INVENTARIO',
    'CREAR_ENTRADA_MANUAL', 'CREAR_GRUPO_INVENTARIO', 'EDITAR_ITEM_INVENTARIO'
}

def check_feature_permission(feature_code):
    """
    Generates a DRF BasePermission class dynamically to strictly check if the 
    authenticated user has the specific feature permission in their RolePermission rules.
    """
    class DynamicFeaturePermission(BasePermission):
        def has_permission(self, request, view):
            if not request.user or not request.user.is_authenticated:
                return False

            try:
                from .models import RolePermission
                cache = getattr(request, '_role_permissions_cache', None)
                if cache is None:
                    rp = RolePermission.objects.filter(role=request.user.role).first()
                    if rp and isinstance(rp.permissions, list):
                        # 'ALL' es un valor heredado que ya no es un permiso real
                        # configurable desde la UI; se ignora una vez que existe
                        # una configuración explícita para el rol.
                        cache = set(rp.permissions)
                        cache.discard('ALL')
                    else:
                        if request.user.role == 'auxiliar':
                            cache = set(AUXILIAR_FINANCIAL_FEATURES)
                        elif request.user.role == 'administrador':
                            # Sin configuración explícita todavía: administrador
                            # mantiene acceso total hasta que se configure el rol.
                            cache = {'ALL'}
                        else:
                            cache = set()
                    request._role_permissions_cache = cache

                if 'ALL' in cache:
                    return True

                aliases = PERMISSION_ALIASES.get(feature_code, {feature_code})
                if any(alias in cache for alias in aliases):
                    return True
            except Exception:
                pass

            return False
            
    return DynamicFeaturePermission
