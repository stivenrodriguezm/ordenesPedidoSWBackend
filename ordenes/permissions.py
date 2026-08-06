from rest_framework.permissions import BasePermission

class IsAdministradorRole(BasePermission):
    """
    Permite acceso solo a usuarios designados explícitamente con el rol administrador.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'administrador')

def check_feature_permission(feature_code):
    """
    Generates a DRF BasePermission class dynamically to strictly check if the 
    authenticated user has the specific feature permission in their RolePermission rules.
    """
    from rest_framework.permissions import BasePermission
    class DynamicFeaturePermission(BasePermission):
        def has_permission(self, request, view):
            if not request.user or not request.user.is_authenticated:
                return False
                
            # Admins bypass role checks
            if request.user.role == 'administrador':
                return True
                
            # For other roles (e.g. vendedor, auxiliar, etc.), look up their dynamic permissions
            try:
                from .models import RolePermission
                # Cachea los permisos del rol en el request para no repetir la query
                cache = getattr(request, '_role_permissions_cache', None)
                if cache is None:
                    rp = RolePermission.objects.filter(role=request.user.role).first()
                    cache = set(rp.permissions) if rp and isinstance(rp.permissions, list) else set()
                    request._role_permissions_cache = cache
                if feature_code in cache:
                    return True
            except Exception:
                pass
                
            return False
            
    return DynamicFeaturePermission
